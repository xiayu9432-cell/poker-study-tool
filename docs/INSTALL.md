# 安装与运行

## 无数据离线演示

只需要 Node.js，不需要 npm 下载依赖。在仓库根目录运行 `node examples/offline-demo.js`。

## Windows 桌面开发

1. 准备 Python 3.12、Node.js 22 LTS 或更新的受支持版本、Windows 桌面环境及 Microsoft Edge WebView2 Runtime。
2. 在根目录创建虚拟环境：`py -3.12 -m venv .venv`。
3. 安装直接依赖：`.\.venv\Scripts\python.exe -m pip install -r requirements.txt`。
4. 依据 `RELEASE.md` 恢复自己有权使用的识别模板、字典和模型，并核对相对路径。
5. 开发入口为 `.\.venv\Scripts\python.exe desktop.py`。这一步可能打开屏幕采集与历史实时功能，应在受控测试环境使用。

本次未安装依赖、未下载 OCR 模型、未编译求解器、未启动桌面采集。依赖清单不是干净环境验证后的锁文件；完整桌面启动和新机器安装仍需单独验证。

`pokerkit` 用于部分规则能力；`scikit-learn` 用于加载已有分类模型。某些模块可选地调用外部求解器，这些程序不在当前包内，也不会随安装命令自动安装。
