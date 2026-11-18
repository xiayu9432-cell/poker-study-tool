# 发布范围与上传方法

## 当前发布内容

这是独立的源码快照，不携带原工作目录的 Git 历史、远程地址、运行数据或微信项目。现有本地工程不受导出操作影响。后续按所有者要求加入了一张原始界面参考图 `docs/images/training-workspace-reference.png`；它是截图排除规则的唯一明确例外，含原始玩家可见资料，未做脱敏。初始导出报告不覆盖这张后加的图片及使用说明。

可立即运行：人工构造手牌的离线演示、选定的无录像轻量测试。

桌面源码已保留，但不是开箱即用的完整桌面发行版。以下资源没有分发：

- `card_templates.json`、`reviewed_card_rank_templates.json`：识别模板，部分可能包含截图衍生内容。
- `hero_avatar.png`、`action-templates/`、`playing-cards/`：头像和界面素材，需核对隐私与使用权。
- `outputs/wepoker-dictionary-rules-v2/` 内字典及分类模型。
- 策略库配置、策略数据库、预计算结果及历史对局资料。
- 外部求解器源码、二进制和大型模型。

更详细的源码资源引用在 `export-report.json`；其中也包含运行时生成文件、可选文件和仅出现文件名的条目，不能把每一项都认定为必需依赖。`source-manifest.json` 记录导出时文件哈希，后续编辑的文档和新增验证报告不在原始快照哈希范围内。

## 上传到新的私有仓库

先在 GitHub 创建空的私有仓库，不要勾选自动生成 README、许可证或 gitignore。发布目录已在整理结束时初始化为独立本地仓库，运行：

```powershell
git status --short
git add .
git diff --cached --stat
git commit -m "Prepare poker study source snapshot"
git remote add origin https://github.com/YOUR_ACCOUNT/poker-study-tool.git
git push -u origin HEAD
```

上面的账户名是占位符。不要把旧项目的仓库地址直接照搬过来，也不要执行 `git add` 指向原项目目录。

## 公开前还需完成

1. 确认源码归属，以及被参考或复制代码的许可证要求；不要直接给整个工程套一个 MIT 许可证。
2. 人工复核 `export-report.json` 的路径或凭据模式命中；自动模式扫描不能证明没有秘密。
3. 确认是否继续以缺少桌面资源的研究源码形式公开；若要发布完整应用，应补充自有或获授权资源并验证干净环境启动。
4. 新增界面演示时使用人工构造数据，或先完成玩家昵称、头像和桌号等信息脱敏。

不以 Star、历史测试数量或单段录像表现宣传 GTO 准确率、实战胜率或盈利收益。
