# DEV-RULES 实现对照表

> **用途**：《开发规范（铁律）》正文一律用**角色称谓**（开发日志、出包脚本、包内门禁脚本……），
> 不写具体路径——这样同一份文件既是本项目的操作手册，也可原样交给外部读者，不必再派生第二版。
> 本表把角色映射回本项目的实际落点，供执行时查。
>
> **归属**：属**开发侧**，不随规范外流、不进任何分发包。
> **同族关系**：`DEV-RULES.md`（规则本体，两端通用）＋ 本表（本项目的落点）。
> **体例**：正文说「记入**开发日志**」，落点就是本表第一行的 `maint/DEVLOG.md`；两处不一致时**以正文的角色为准**，
> 改本表，不得反过来改正文去迁就路径。
>
> **维护**：新增或改名任何被正文引用的文件／脚本／常量，须同步改本表；改漏由 `maint/tools/check-dev-rules.py`
> 的「对照表完整性」一维兜底（表内路径须真实存在）。

## 一、文件与目录

| 正文角色称谓 | 本项目实际落点 | 说明 |
|---|---|---|
| 开发日志 | `maint/DEVLOG.md` | 流水，按时间倒序；每次改动前先记一行（18.1） |
| 遗留清单 | `maint/OPEN-ISSUES.md` | 只放「转下轮」未闭环项；与流水分离，防读到过期表 |
| 变更记录 | `dev/CHANGELOG.md` | 按版本记「改了什么」，含实现细节与踩坑 |
| 开发目录 / 开发侧 | `dev/`（本文件、变更记录、发布脚本、技能源）＋ `maint/`（日志、临时工具、草稿、测试数据） | 两侧都**不进包** |
| 发布目录 | `dist/` | 分发包 `.zip`／`.skill` 落地处；台账的真源 |
| 技能目录 / 技能本体 | `doc-compliance-review/` | 唯一进包的目录 |
| 素材目录 | `doc-compliance-review/samples/` | 随包但须逐条准入登记（9.4） |
| 准入清单 | `maint/samples-manifest.json` | 字段 `name`／`purpose`／`reason`；出包前核验 |
| 铁律本体 | `dev/DEV-RULES.md` | 即本表同目录那一份 |
| 铁律在线版 | `maint/scratch/DEV-RULES.online.md` | 由 `maint/tools/make-online-md.py` 派生，去锚点纯文字大纲 |
| 产出物台账 | `/workspace/产出物台账.md` | 派生件，由 `maint/tools/gen-ledger.py` 全量重建 |

## 二、脚本

### 开发侧（`maint/tools/`，均不进包）

| 正文角色称谓 | 脚本 | 职责 |
|---|---|---|
| 铁律自检 | `check-dev-rules.py` | 铁律全文十八维自检；**唯一**判铁律自身合规的入口（维数以脚本实际输出为准，2026-11-06 校正：原文写「十六维」，与实际 18 维不符） |
| 分离守卫 | `check-separation.py` | 白名单目录混入开发资料、未登记素材、开发资料越界；发布链内调用 |
| 元自测脚本 | `meta-smoke-dev-rules.py` | 自检脚本自身的注入式反向用例（打瘸后须红） |
| 台账生成器 | `gen-ledger.py` | 全量重建产出物台账，**不含任何断言**（故 24.3 第 23 行记「人工」） |
| 在线版生成器 | `make-online-md.py` | 铁律 → 去锚点纯文字大纲 |
| 重排同步工具 | `sync-clause-refs.py` | 按编号映射表批量改各文件里的条款引用 |
| 建库脚本 | `build-legal-db.py` | 法规库多源抓取与交叉验证，写 `core/legal-articles.json` |

### 技能包内（`doc-compliance-review/scripts/`，进包）

| 正文角色称谓 | 脚本 | 职责 |
|---|---|---|
| 包内门禁脚本 / 结构校验守卫 | `check.py` | 包内全部结构、数字口径、安全、联网分级的断言；退出码即门禁 |
| 包内冒烟脚本 | `smoke-test.py` | 行为级回归用例（每项带对照组、可注入打瘸） |
| 出包脚本 | `pack.py` | 产物命名、白名单取件、准入核验、自测 |
| 文档生成脚本 | `make-docx.py` | 交付物生成（修订版／批注版／红线版／报告） |
| 内容守卫脚本 | `guard.py` | 生成前的规则化拦截 |
| 版本脚本 | `version.py` | 版本身份证、更新检测、本地升级 |
| 起草指南 | `drafting-guide.md` | 起草口径与话术 |

### 发布侧

| 正文角色称谓 | 脚本 | 职责 |
|---|---|---|
| 发布脚本 | `dev/publish.py` | 一条链跑完同步 → 校验 → 出包 → 落 `dist/` |

## 三、包内关键常量与函数（`doc-compliance-review/scripts/`）

正文提到这些时用的是角色称谓，此处给实际名。

| 正文角色称谓 | 实际名 | 所在 | 用途 |
|---|---|---|---|
| 安全机制矩阵常量 | `SEC_MATRIX` | `check.py` | 安全机制登记表（索引，非第二真源） |
| 行业种子表 | `SEED_INDUSTRIES` | `check.py`、`guard.py` | 内置行业库清单 |
| 随包白名单 | `FULL_DIRS` | `pack.py` | 整目录随包的名单（`core`／`industries`／…） |
| 禁用写法清单 | `FORBID` | `check.py` | 陈旧表述、写死数字等的禁用写法注册表 |
| 联网分级判定 | `_net_tiers()` | `check.py` | 解析各脚本文件头的 `# net-tier:` 自标 |
| 文档联网名单 | `_doc_net_tiers()` | `check.py` | 文档里声明的联网名单 |
| 联网分级检查 | `check_net_tiers()` | `check.py` | 五条断言：无缺标／L0 越界／在线档空头／L3 真 import／文档与代码逐档一致 |
| 联网边界检查 | `_check_online_gate()` | `check.py` | 在线档的边界断言 |
| 安全机制逐条检查 | `check_security_matrix()` | `check.py` | 登记表逐条对照私有实现 |
| 安全机制检查 | `check_security()` | `check.py` | 安全引擎总入口 |
| 数字口径检查 | `check_doc_number_caliber()` | `check.py` | 文档里的数字与真源实算比对 |
| 版本串一致性检查 | `check_version_consistency()` | `check.py` | 包内版本串三处一致 |
| 清单版本检查 | `check_manifest_version()` | `check.py` | 清单与包版本对齐 |
| 文档一致性检查 | `_check_doc_consistency()` | `check.py` | 文档表述与实现一致 |
| 子进程编码检查 | `_check_subprocess_encoding()` | `check.py` | `text=True` 必带 `encoding` |
| 提问结构检查 | `_check_questionnaire_libraries()` | `check.py` | 一问一维度、禁组合选项 |
| 能力计数检查 | `_check_capability_count()` | `check.py` | 能力表条数与真源一致 |
| 字节码防护检查 | `_check_no_bytecode()`、`bytecode_leaks()` | `check.py` | 缓存泄漏；两处共用**同一实现** |
| 脚本清点函数 | `_script_files()` | `check.py` | 枚举包内脚本（判据按首个业务 import 定位） |
| UTF-8 输出环境 | `_utf8_env()` | `check.py`、`verify-dist.py` | 子进程统一 `PYTHONIOENCODING=utf-8` |
| 格式清单参数 | `--formats` | `make-docx.py` | 支持的格式清单；数字口径的真源 |

## 四、约定标记

| 正文讲的约定 | 实际做法 | 判据在哪 |
|---|---|---|
| 脚本自标联网档位 | 每个脚本文件头一行 `# net-tier: L0`～`L3` | `check.py` → `check_net_tiers()`（无中央登记表，第 12 条） |
| 出域档 L0—L3 | L0 全离线／L1 在线只读／L2 只读＋脱敏／L3 明示上送 | `DEV-RULES.md` 第 26 条；代码自标为准 |
| 打瘸点清单 | `maint/tools/check-dev-rules.py` 的 `CRIPPLES`（打瘸动作）与 `CRIPPLES_FN`（打瘸函数）两张表 | 元自测按表遍历，任一项打瘸后须红 |
| 述史豁免 | 历史记录（`CHANGELOG`／`VERSION.md`／`DEVLOG` 旧条目）回改即造假 | 铁律自检「沿革文本豁免」 |
| 〔述史〕标记 | 只对**活文档**里保留的旧版表述加标记 | 第 22 条表第 11 行 |

## 五、本表自身的守卫

`maint/tools/check-dev-rules.py` 的「对照表完整性」一维核两件事：

1. **表内出现的路径必须真实存在**（防改名后表留旧路径，读者照着找不到）；
2. **正文不得出现本表左列以外的实现名**（防改正文时把路径又写回去，两份重新漂开）。

第 2 条是这次结构改造的关门判据——原先靠「改了源记得重跑生成器」维持两份一致，靠不住；
现在只有一份正文，风险换成了「正文被人改回带路径」，改由自检当场拦。
