# -*- coding: utf-8 -*-
"""
折叠中文通信器外壳 —— Fusion 360 参数化建模脚本

用法：Utilities → Add-Ins → Scripts → Open Script Folder
     把 Fusion360_Communicator 文件夹拷进去，选中 Script 运行。

生成 4 个实体（自动排成一排，方便一起导出 STL）：
  上壳 / 上背板 / 下壳 / 下背板

尺寸与 STL 版一致；改下面的参数后重新运行即可。
屏幕模块、键盘、ESP32 的外形是暂定值，请按手上实物调整。
"""
import math
import traceback

import adsk.core
import adsk.fusion

# ------------------------------------------------------------------ 参数
W, D = 80.0, 50.0          # 整机外形
WALL, FLOOR = 2.0, 2.0     # 壁厚 / 面板厚
UP_H, LOW_H = 20.0, 26.0   # 上壳 / 下壳厚
WIN_W, WIN_H = 56.0, 28.5  # 屏幕视窗
MOD_W, MOD_H = 60.5, 36.5  # 2.42" OLED 模块
KEY = 45.0                 # 4x4 薄膜键盘
USB_W, USB_H = 9.0, 3.2
SW_W, SW_H = 7.0, 3.5
HINGE_W, HINGE_L, HINGE_D = 10.5, 15.5, 1.2
POST_R, POST_HOLE = 2.5, 0.9   # M2 螺纹柱

EXPORT_STL = False
STL_DIR = "C:/Users/sally/Desktop/DIY_stl/通信器"


def _vi(v):
    return adsk.core.ValueInput.createByReal(float(v))


def _plane(root, z):
    pi = root.constructionPlanes.createInput()
    pi.setByOffset(root.xYConstructionPlane, _vi(z))
    return root.constructionPlanes.add(pi)


def _rect_body(root, x0, y0, z0, x1, y1, z1, name=None):
    sk = root.sketches.add(_plane(root, z0))
    sk.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(x0, y0, 0),
        adsk.core.Point3D.create(x1, y1, 0))
    prof = sk.profiles.item(0)
    ext = root.features.extrudeFeatures
    inp = ext.createInput(prof, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    inp.setDistanceExtent(False, _vi(z1 - z0))
    body = ext.add(inp).bodies.item(0)
    if name:
        body.name = name
    return body


def _cyl_body(root, cx, cy, z0, z1, r, name=None):
    sk = root.sketches.add(_plane(root, z0))
    sk.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(cx, cy, 0), r)
    prof = sk.profiles.item(0)
    ext = root.features.extrudeFeatures
    inp = ext.createInput(prof, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    inp.setDistanceExtent(False, _vi(z1 - z0))
    body = ext.add(inp).bodies.item(0)
    if name:
        body.name = name
    return body


def _cut(root, target, tools):
    if not tools:
        return
    comb = root.features.combineFeatures
    coll = adsk.core.ObjectCollection.create()
    for t in tools:
        coll.add(t)
    inp = comb.createInput(target, coll)
    inp.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
    inp.isKeepToolBodies = False
    comb.add(inp)


def _join(root, target, tools):
    if not tools:
        return
    comb = root.features.combineFeatures
    coll = adsk.core.ObjectCollection.create()
    for t in tools:
        coll.add(t)
    inp = comb.createInput(target, coll)
    inp.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
    inp.isKeepToolBodies = False
    comb.add(inp)


def _frame(root, H, ox):
    """做一个内面有整块面板、背面开口的框架。"""
    outer = _rect_body(root, ox - W / 2, -D / 2, 0, ox + W / 2, D / 2, H, "外壳")
    cave = _rect_body(root, ox - W / 2 + WALL, -D / 2 + WALL, -1,
                      ox + W / 2 - WALL, D / 2 - WALL, H - FLOOR, "内腔")
    _cut(root, outer, [cave])
    # 四角螺纹柱 + 底孔
    posts, holes = [], []
    for sx in (-1, 1):
        for sy in (-1, 1):
            px = ox + sx * (W / 2 - WALL - 3)
            py = sy * (D / 2 - WALL - 3)
            posts.append(_cyl_body(root, px, py, 0, H - FLOOR, POST_R))
            holes.append(_cyl_body(root, px, py, -1, H - FLOOR + 1, POST_HOLE))
    _join(root, outer, posts)
    _cut(root, outer, holes)
    return outer


def _hinge(root, body, H, ox):
    zc = H - 1 - HINGE_L / 2
    tools = []
    for sx in (-1, 1):
        px = ox + sx * W / 4
        x0, x1 = px - HINGE_W / 2, px + HINGE_W / 2
        y0 = -D / 2
        tools.append(_rect_body(root, x0, y0, zc - HINGE_L / 2,
                                x1, y0 + HINGE_D, zc + HINGE_L / 2))
        for dz in (-5, 5):
            tools.append(_cyl_body(root, px, y0 - 1, zc + dz - 1,
                                   zc + dz + 1, 1.1))
    _cut(root, body, tools)


def build_communicator(root, ox):
    made = []
    # 上壳
    up = _frame(root, UP_H, ox)
    up.name = "通信器_上壳"
    tools = [
        _rect_body(root, ox - WIN_W / 2, -WIN_H / 2, UP_H - FLOOR - 1,
                   ox + WIN_W / 2, WIN_H / 2, UP_H - FLOOR + 1),
        _rect_body(root, ox - 6, -D / 2 - 1, 3, ox + 6, -D / 2 + WALL + 1, 5),
    ]
    for sx in (-1, 1):
        for sy in (-1, 1):
            tools.append(_cyl_body(root, ox + sx * (MOD_W / 2 + 1.5),
                                   sy * (MOD_H / 2 + 1.5),
                                   UP_H - FLOOR - 5, UP_H - FLOOR, 1.5))
    _cut(root, up, tools)
    _hinge(root, up, UP_H, ox)
    made.append(up)

    # 下壳
    lo = _frame(root, LOW_H, ox)
    lo.name = "通信器_下壳"
    tools = [
        _rect_body(root, ox - KEY / 2, -KEY / 2, LOW_H - FLOOR - 1,
                   ox + KEY / 2, KEY / 2, LOW_H - FLOOR + 1),
        _rect_body(root, ox - KEY / 2 - 1.5, -KEY / 2 - 1.5, LOW_H - FLOOR - 1.5,
                   ox + KEY / 2 + 1.5, KEY / 2 + 1.5, LOW_H - FLOOR),
        _rect_body(root, ox + W / 2 - 2, -USB_W / 2, 9.4, ox + W / 2 + 2, USB_W / 2, 12.6),
        _rect_body(root, ox - W / 2 - 2, -SW_W / 2, 9.25, ox - W / 2 + 2, SW_W / 2, 12.75),
        _rect_body(root, ox - 6, -D / 2 - 1, 3, ox + 6, -D / 2 + WALL + 1, 5),
    ]
    _cut(root, lo, tools)
    # 电池限位墙
    rails = [
        _rect_body(root, ox - 20.6, 15.0, 0, ox + 20.6, 16.2, 5),
        _rect_body(root, ox - 20.6, -16.2, 0, ox + 20.6, -15.0, 5),
        _rect_body(root, ox + 20.0, -15.0, 0, ox + 21.2, 15.0, 5),
        _rect_body(root, ox - 21.2, -15.0, 0, ox - 20.0, 15.0, 5),
    ]
    _join(root, lo, rails)
    _hinge(root, lo, LOW_H, ox)
    made.append(lo)

    # 背板
    for nm, H in (("通信器_上背板", UP_H), ("通信器_下背板", LOW_H)):
        plate = _rect_body(root, ox - W / 2 + 0.1, -D / 2 + 0.1, -2,
                           ox + W / 2 - 0.1, D / 2 - 0.1, 0, nm)
        tools = []
        for sx in (-1, 1):
            for sy in (-1, 1):
                px = ox + sx * (W / 2 - WALL - 3)
                py = sy * (D / 2 - WALL - 3)
                tools.append(_cyl_body(root, px, py, -3, 1, 1.1))
                tools.append(_cyl_body(root, px, py, -2.2, -1.0, 2.0))
        _cut(root, plate, tools)
        made.append(plate)
    return made


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
        root.name = "通信器_外壳"

        bodies = build_communicator(root, 0.0)
        log.append("[OK] 生成 %d 个实体" % len(bodies))
        for b in bodies:
            log.append("   - %s  体积 %.0f mm3" % (b.name, b.volume))

        if EXPORT_STL:
            import os
            os.makedirs(STL_DIR, exist_ok=True)
            em = design.exportManager
            for b in bodies:
                opt = em.createSTLExportOptions(b, os.path.join(STL_DIR, b.name + ".stl"))
                opt.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementMedium
                em.execute(opt)
            log.append("[OK] STL 已导出到 " + STL_DIR)

        if ui:
            ui.messageBox("\n".join(log), "通信器外壳 · 生成完成")
    except Exception:
        if ui:
            ui.messageBox("脚本出错：\n" + traceback.format_exc(), "通信器外壳")
