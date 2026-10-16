# -*- coding: utf-8 -*-
"""
1:1000 齐柏林飞艇 LZ127 —— Fusion 360 参数化建模脚本

怎么用：
  1. 打开 Fusion 360
  2. 工具栏 Utilities（实用程序）→ Add-Ins（附加模块）→ Scripts（脚本）标签
  3. 点 "Open Script Folder"（打开脚本文件夹），把 Zeppelin_LZ127 这个文件夹整个拷进去
  4. 回到对话框刷新一下，选中 Zeppelin_LZ127，点 Run（运行）

它会在当前设计里生成：
  - 艇体回转实体（按纵向轮廓放样）
  - 16 道隔框环（可当骨架参考，也可以直接 3D 打印）
  - 可选：导出 STL

参数都在下面的“参数”一节，改完重新运行即可。
注意：艇体纵向轮廓是近似放样（文档未提供原始型线图）。
尾翼没有做——文档只给了“全高 35 mm”，缺展长/弦长/根部站位，见 README 的说明。
"""

import math
import traceback

import adsk.core
import adsk.fusion

# ------------------------------------------------------------------ 参数
# 想换比例只改 SCALE 就行：1:1000 → 1.0/1000.0，1:500 → 1.0/500.0
SCALE = 1.0 / 1000.0
REAL_LEN_M = 236.6          # LZ127 实机全长（米）
REAL_DIA_M = 30.5           # 实机最大直径（米）

LEN_MM = REAL_LEN_M * 1000.0 * SCALE        # 模型全长（mm）
MAX_DIA_MM = REAL_DIA_M * 1000.0 * SCALE    # 模型最大直径（mm）

MAKE_HULL = True            # 生成艇体
MAKE_FRAMES = True          # 生成隔框环
FRAME_W = 0.6               # 隔框轴向宽度 mm
FRAME_T = 0.4               # 隔框径向厚度 mm

EXPORT_STL = False          # 改成 True 并把下面路径换成你自己的目录
STL_DIR = "C:/Users/<user>/Desktop/DIY_stl"

# 隔框站位（t = 距离艇首的比例），要和图纸里的 F01-F16 对上
STATIONS = [0.050, 0.090, 0.135, 0.185, 0.240, 0.300, 0.365, 0.435,
            0.505, 0.575, 0.645, 0.712, 0.775, 0.833, 0.885, 0.930]

# 纵向轮廓控制点 (t, r/R)
CTRL = [
    (0.000, 0.000), (0.015, 0.250), (0.040, 0.430), (0.080, 0.585),
    (0.140, 0.735), (0.220, 0.870), (0.310, 0.955), (0.420, 1.000),
    (0.520, 0.988), (0.620, 0.945), (0.700, 0.880), (0.770, 0.790),
    (0.840, 0.660), (0.890, 0.545), (0.930, 0.435), (0.960, 0.325),
    (0.982, 0.205), (1.000, 0.000),
]


# ------------------------------------------------------------- PCHIP 插值
def _pchip_slopes(x, y):
    h = [x[i + 1] - x[i] for i in range(len(x) - 1)]
    d = [(y[i + 1] - y[i]) / h[i] for i in range(len(x) - 1)]
    n = len(x)
    m = [0.0] * n

    def end_slope(h0, h1, d0, d1):
        s = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
        if s * d0 <= 0:
            return 0.0
        if d0 * d1 < 0 and abs(s) > abs(3 * d0):
            return 3 * d0
        return s

    for i in range(1, n - 1):
        if d[i - 1] * d[i] <= 0:
            m[i] = 0.0
        else:
            w1 = 2 * h[i] + h[i - 1]
            w2 = h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
    m[0] = end_slope(h[0], h[1], d[0], d[1])
    m[-1] = end_slope(h[-1], h[-2], d[-1], d[-2])
    return m


_CX = [p[0] for p in CTRL]
_CY = [p[1] for p in CTRL]
_CM = _pchip_slopes(_CX, _CY)


def radius_at(t):
    """t 处的艇体半径（mm）。"""
    t = min(max(t, 0.0), 1.0)
    i = 0
    for k in range(len(_CX) - 1):
        if _CX[k] <= t <= _CX[k + 1]:
            i = k
            break
    else:
        i = len(_CX) - 2
    h = _CX[i + 1] - _CX[i]
    u = (t - _CX[i]) / h
    h00 = 2 * u ** 3 - 3 * u ** 2 + 1
    h10 = u ** 3 - 2 * u ** 2 + u
    h01 = -2 * u ** 3 + 3 * u ** 2
    h11 = u ** 3 - u ** 2
    v = h00 * _CY[i] + h10 * h * _CM[i] + h01 * _CY[i + 1] + h11 * h * _CM[i + 1]
    return max(v, 0.0) * (MAX_DIA_MM / 2.0)


def _vi(s):
    return adsk.core.ValueInput.createByString(s)


def build_hull(root):
    """在 XY 平面画纵向轮廓，绕 X 轴回转成艇体。"""
    sk = root.sketches.add(root.xYConstructionPlane)
    sk.name = "艇体轮廓"
    pts = adsk.core.ObjectCollection.create()
    for t, _ in CTRL:
        pts.add(adsk.core.Point3D.create(t * LEN_MM, radius_at(t), 0))
    spline = sk.sketchCurves.sketchFittedSplines.add(pts)
    axis = sk.sketchCurves.sketchLines.addByTwoPoints(
        adsk.core.Point3D.create(0, 0, 0),
        adsk.core.Point3D.create(LEN_MM, 0, 0))
    prof = sk.profiles.item(0)
    revs = root.features.revolveFeatures
    inp = revs.createInput(prof, axis, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    inp.setAngleExtent(False, _vi("360 deg"))
    body = revs.add(inp).bodies.item(0)
    body.name = "艇体"
    return body


def build_frames(root):
    """每道隔框：在 XY 平面画一个小矩形，绕全局 X 轴回转 360 度成环。"""
    made = 0
    for i, t in enumerate(STATIONS, start=1):
        r = radius_at(t)
        x = t * LEN_MM
        sk = root.sketches.add(root.xYConstructionPlane)
        sk.name = "隔框 F%02d" % i
        y0 = r
        y1 = r + FRAME_T
        p1 = adsk.core.Point3D.create(x - FRAME_W / 2.0, y0, 0)
        p2 = adsk.core.Point3D.create(x + FRAME_W / 2.0, y0, 0)
        p3 = adsk.core.Point3D.create(x + FRAME_W / 2.0, y1, 0)
        p4 = adsk.core.Point3D.create(x - FRAME_W / 2.0, y1, 0)
        sk.sketchCurves.sketchLines.addByTwoPoints(p1, p2)
        sk.sketchCurves.sketchLines.addByTwoPoints(p2, p3)
        sk.sketchCurves.sketchLines.addByTwoPoints(p3, p4)
        sk.sketchCurves.sketchLines.addByTwoPoints(p4, p1)
        prof = sk.profiles.item(0)
        revs = root.features.revolveFeatures
        inp = revs.createInput(prof, root.xConstructionAxis,
                               adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        inp.setAngleExtent(False, _vi("360 deg"))
        b = revs.add(inp).bodies.item(0)
        b.name = "隔框 F%02d" % i
        made += 1
    return made


def export_stls(root, folder):
    import os
    os.makedirs(folder, exist_ok=True)
    em = root.parentDesign.exportManager
    for i in range(root.bRepBodies.count):
        b = root.bRepBodies.item(i)
        path = os.path.join(folder, b.name.replace(" ", "_") + ".stl")
        opt = em.createSTLExportOptions(b, path)
        opt.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementMedium
        em.execute(opt)
    return root.bRepBodies.count


def run(context):
    ui = None
    log = []
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(app.activeProduct)
        design.designType = adsk.fusion.DesignTypes.ParametricDesignType
        root = design.rootComponent
        root.name = "LZ127_1to1000"

        if MAKE_HULL:
            try:
                b = build_hull(root)
                log.append("[OK] 艇体：长 %.1f mm，最大直径 %.1f mm"
                           % (b.boundingBox.maxPoint.x - b.boundingBox.minPoint.x,
                              2 * radius_at(0.42)))
            except Exception as e:
                log.append("[失败] 艇体：%s" % e)

        if MAKE_FRAMES:
            try:
                n = build_frames(root)
                log.append("[OK] 隔框 %d 道（宽 %.2f / 厚 %.2f mm）" % (n, FRAME_W, FRAME_T))
            except Exception as e:
                log.append("[失败] 隔框：%s" % e)

        if EXPORT_STL:
            try:
                n = export_stls(root, STL_DIR)
                log.append("[OK] 已导出 %d 个 STL 到 %s" % (n, STL_DIR))
            except Exception as e:
                log.append("[失败] 导出 STL：%s" % e)

        log.append("")
        log.append("提示：尾翼未生成——文档只给了全高 35 mm，")
        log.append("缺尾翼展长、弦长、根部站位，定了这三个数就能补上。")
        if ui:
            ui.messageBox("\n".join(log), "1:1000 齐柏林飞艇 · 生成完成")
    except Exception:
        if ui:
            ui.messageBox("脚本出错：\n" + traceback.format_exc(), "1:1000 齐柏林飞艇")
