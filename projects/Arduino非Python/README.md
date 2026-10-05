# Arduino非Python

> ⚙️ 本文由自动推送于 2026-10-05 生成，内容取自讨论开头，尚未人工整理。
> 入选理由：标题:Arduino、需求:arduino

- 讨论日期：2026-07-12
- 消息数：2

## 原始需求

arduino编程语言是phthon吗

## 初步方案

**不是的，Arduino编程语言不是Python。**

Arduino的官方编程语言是基于C/C++的[reference:0][reference:1][reference:2]。虽然名字里带“语言”，但它本质上是在C/C++的基础上，封装了一些便于控制硬件的函数和库[reference:3][reference:4]。

不过，这并不意味着Python和Arduino毫无关系。实际上，有几种方式可以让Python与Arduino协同工作：

### 🐍 Python如何与Arduino互动

1.  **在PC端用Python控制Arduino**：这是最常用的方式。Arduino板上运行C++程序，通过USB或串口与电脑通信；电脑上的Python程序（使用`pySerial`等库[reference:5]）接收数据或发送指令[reference:6]。这适用于需要Python处理复杂任务（如数据分析、GUI界面）的场景[reference:7]。
2.  **在Arduino上运行Python (MicroPython)**：对于性能更强的Arduino板（如Portenta H7[reference:8]），可以刷入**MicroPython**（专为微控制器设计的精简版Python[reference:9]），然后用Python直接给硬件编程[reference:10]。
3.  **使用Python库直接生成Arduino代码**：有一些第三方库（如`Pyduino`[reference:11]）尝试将Python代码转换为Arduino的C++代码，但这种方式并非主流。

### 📝 总结

| 方面 | Arduino 原生语言 | Python |
| :--- | :--- | :--- |
| **本质** | 基于 **C/C++** 的“硬件语言”[reference:12] | 通用编程语言 |
| **运行环境** | 在 **Arduino 板**的微控制器上直接运行[reference:13] | 通常在 **电脑** 上运行[reference:14] |
| **主要用途** | 直接、实时地控制传感器、电机等硬件[reference:15] | 数据分析、AI、Web开发等复杂任务[reference:16] |

简单来说，如果你是想直接给Arduino板子编程，用的是**C/C++**；如果你是想在电脑上通过Python间接控制Arduino，那是**Python调用Arduino**。这两者不是一回事。

如果你想了解如何用Python控制Arduino的代码示例，或者想看看MicroPython的具体用法，可以随时再问我。

## 待办

- [ ] 整理成正式项目文档（补材料清单、规格、时间安排）
- [ ] 补充后续讨论里新增的结论
