# 系统架构（通用层 v0.1）

> **平台无关文档**：描述"系统由什么组成、数据怎么流、状态怎么走"，不绑定任何引擎或平台。
> 目标平台 = 千星奇域 / Steam / 移动端皆可用；平台差异集中在 §7 的适配层，**逻辑层不动**。
> 配套文档：数值模型 `design/balance-model.md`；千星奇域实现映射 `design/roguelike-survival.md`。

---

## 0. 分层原则（最重要的一节）

```
L0 配置数据    数值表（CSV/JSON）—— 改数值不改逻辑
L1 逻辑层      纯数据变换：战斗结算、波次调度、经济、商店、天赋 —— 不碰表现、不碰平台
L2 表现层      特效、UI、镜头、音效、飘字 —— 只订阅 L1 的事件
L3 平台适配层  输入、存档、排行榜、时间、随机数 —— 每个平台换一份实现
```

**硬规则**

1. **L1 不得直接调用 L2/L3**，只能发出事件；由适配层订阅
2. **L1 不含任何绝对数值**，一切读 L0
3. **L3 是唯一允许出现平台名的层** → 移植时只重写 L3

> 落地时：可视化脚本平台（如千星沙箱）里 L1 = 一组复合节点/节点图分组，L2 = 界面控件与特效，L3 = 平台节点；代码平台里 L1 = 系统类，L2 = 视图，L3 = 服务接口。**架构不变。**
>
> 📌 **千星奇域的实际落地（2026.10.01 暂定「C 混合」）**：L1（含权威数据）= **服务器节点图**；L2 = **客户端控件 + 客户端 Lua（Lua 5.3）**；L3 = 平台节点与外围系统（排行榜 / 成就 / 结算）。
> **L1 ↔ L2 桥接** = 上行 `ServerSignal:SendSignal()` + 下行服务器节点【发送客户端脚本信号】/ `RegisterServerSignalHandler`，只读数据走 `GetGlobalCustomVariableValue`（**支持结构体**）。
> ⚠️ 联机信号**延迟下限 100 ms**（按事件同步，不按帧）；**传送 / 重连会销毁所有客户端控件** → **L2 必须可重建**，状态一律留在 L1。

---

## 1. 模块清单

| 模块 | 职责 | 依赖 | 层 |
| --- | --- | --- | --- |
| **Battle** | 伤害结算、命中判定、死亡处理 | 数据模型、L0 | L1 |
| **UnitAI** | **阵营 A / 阵营 B 的单位**：沿**路径**推进、索敌、攻击；到达对方基地后**持续攻击直到死亡** | Battle | L1 |
| **Spawner** | **每阵营对称**：该阵营的建筑按 `interval` 产出单位 | UnitAI、L0 | L1 |
| **FactionDriver** | **阵营驱动源（可替换！）**：`AIDriver`（v1 单机：定时刷兵 + 档位强度曲线）/ `PlayerDriver`（未来联机：该玩家的建造与技能输入）→ 两者输出**同一套「指令流」**（建造请求 / 技能释放 / 出兵），L1 不关心指令来源 | Spawner、Build、Skill | L1 |
| **Economy** | 金币收入（含**精炼厂冻结与增益**）、支出 | L0 | L1 |
| **Build** | 槽位管理（**内圈 / 外圈**）、建造校验（占用 / 科技前置 / 花费）、用 **`创建元件`** 定点创建建筑、**建筑血量与摧毁、槽位释放** | Economy、L0 | L1 |
| **Tech** | 科技解锁（T2 / T3 前置） | L0 | L1 |
| **Commander** | **指挥官候选抽取**（run seed 确定性随机，从全局池抽 3 个）与**1 被动 + 1 主动**注入；**实现上绑定到玩家的「职业」**（D-R11：职业属性/技能/镜头模板都由职业承载） | L0 | L1 |
| **PlayerActor** | 玩家的行走能力（**可自由行走**）、**禁用攻击**、**取消与单位/建筑的碰撞**（D-R12） | L1 | L1 |
| **Skill** | **主动技能**的冷却与释放（效果由 `active_skills.csv` 配置；纯冷却、无目标释放） | Battle、Economy | L1 |
| **Base** | 双方基地血量、**基地防御火力**、胜负判定 | Battle | L1 |
| **RunState** | 一局状态机（§2）、结算触发 | 以上全部 | L1 |
| **Faction** | **派系选择**（开局）：注入该派系的**兵种池 / 外观**，并让所有参数读取走 **`get_param(key, faction_id)`**（基础值 × 派系修正）；整局不可变更 | L0 | L1 |
| **HUD** | 金币 / 收入、基地血量、敌方档位、技能冷却、**冻结倒计时** | 订阅事件 | L2 |
| **BuildUI** | 建造面板：槽位点击、建筑列表、科技前置提示、花费校验反馈 | 订阅事件 | L2 |
| **SkillUI** | 技能栏与冷却显示 | 订阅事件 | L2 |
| **ResultUI** | 结算（胜 / 负、用时、剩余基地血量） | 订阅事件 | L2 |
| **Camera/View** | **静止角色锚 + 俯视镜头**、单位与建筑视图 | — | L2 |
| **InputAdapter** | 点击 / 光标输入（**本玩法无移动操作**） | — | L3 |
| **SaveAdapter** | 存档（本地/平台云） | — | L3 |
| **RankAdapter** | 排行榜写入 | — | L3 |
| **Clock/RNG** | 时间与确定性随机 | — | L3 |

> 成就（Achievements）**首图不做**，但架构上预留 RankAdapter 同级的 `AchievementAdapter` 位置。

---

## 1.5 对称阵营结构（为联机对战预留）

> **原则：架构里没有"我方 / 敌方"，只有「阵营 A / 阵营 B」两个对等主体。**
> 单机不是"另一种结构"，而是**两个阵营都存在、其中一个恰好由本机玩家操作**的特例。

| 维度 | 单机（v1） | 联机对战（未来） | 架构上必须怎么做 |
| --- | --- | --- | --- |
| **阵营数** | 2（A = 玩家，B = 系统） | 2（各自一名玩家） | 一律按 `faction_id` 索引，**不写 `self/enemy`** |
| **驱动源** | A = `PlayerDriver`；B = `AIDriver` | 双方都是 `PlayerDriver` | `FactionRuntime.driver` 字段 + `FactionDriver` 接口（输出同一套指令流） |
| **派系选择** | 玩家选；B 固定为"敌对派系"（F1） | **双方各自选**（允许同派系内战） | 派系是**每阵营的字段**，不是全局单例 |
| **指挥官** | 玩家选；B 不选 | **双方各自选**（各自抽 3 选 1） | `commander_id` 挂在 `FactionRuntime` 上，**可为空** |
| **收入 / 槽位 / 建筑** | A 有完整经济；B 只刷兵 | **双方都有完整经济** | 经济与槽位**天然属于 `FactionRuntime`** → B 的经济 v1 只是"没启用"，不是"不存在" |
| **巡逻方向** | 模板 1 = 向 B 基地、模板 2 = 向 A 基地 | 同上 | **方向不做全局假设** → 按 `faction_id → 巡逻模板序号` 映射 |
| **UI（客户端 Lua）** | 一套（本机玩家） | **每客户端一套**（客户端脚本本就每客户端一份 ✅） | HUD 只渲染"本机所属阵营"的数据；读全局自定义变量时必须带 `faction_id` |
| **平台阵营系统** | 用平台「阵营」承载 A/B 与**单向**敌对关系 | 同 | 用平台阵营，**不自造"我方/敌方"标记**（官方阵营系统本就是为"组队竞技"设计的） |
| **结算 / 胜负** | 推掉 B 基地 | 同（或加时间上限比血量） | 判定按"**所有**阵营的基地血量"写 → 将来能扩展到 >2 方 |

**⚠️ v1 里唯一的"不对称"是刻意的范围控制，不是架构假设**

- v1 的 B 阵营**不建建筑、不投资、不选指挥官** —— 只按 12 档曲线刷兵（`AIDriver` 的最简实现）
- 因此 v1 要靠**敌方档位曲线**补偿"玩家有被动 + 主动"的优势（见 `balance-model.md` §8）
- **联机时这条补偿自动消失**（双方对等）→ 所以曲线设计要留一条"**基础压力**"线，而不是把数值调到"刚好抵住玩家的被动 + 主动"（否则联机时两边都太弱）

**❗ 单机阶段不要做的三件"省事但堵路"的事**

1. ❌ 不要把 `self/enemy` 写进**配置表字段名或节点图变量名** → 一律用 `faction_id`
2. ❌ 不要假设"只有一个玩家" → 玩家实体与阵营的对应关系**走查询**，不要用"关卡里唯一的角色"
3. ❌ 不要把巡逻方向**写死**成"永远朝 B 基地" → 走 `faction_id → 模板序号` 映射

---

## 2. 一局状态机

```
Boot → RunInit → FactionSelect → CommanderSelect → Battle（持续，无波次） → Settle → Result → Boot
                                                       ├── IncomeTick    （每秒：金币收入，含冻结判定）
                                                       ├── SpawnTick     （各建筑按 interval 产兵）
                                                       ├── EnemyTierTick （每 60 秒升一档敌方强度）
                                                       ├── SkillTick     （指挥官技能的冷却）
                                                       └── WinCheck      （任一方基地血量 ≤ 0，或 720 秒到）
```

| 状态 | 进入条件 | 退出条件 | 备注 |
| --- | --- | --- | --- |
| `RunInit` | 关卡开始 | 初始化完成 | 设 `gold_start`、清空槽位、初始化基地血量 |
| `FactionSelect` | 初始化完成 | 玩家选定 1 个派系 | **整局不可变更**；决定兵种池（D-R9）。⚠️ 与平台「阵营」（战斗关系）不是一回事 |
| `CommanderSelect` | 派系选定 | 玩家选定 1 个指挥官 | 从池中**确定性随机抽 3 个候选**（D-R10）；决定技能套组 |
| `Battle` | 指挥官选定 | **任一方基地血量 ≤ 0** 或 **计时到 720 秒** | ⚠️ **没有"波次"概念** —— 五个不同周期的 tick 并行推进 |
| `Settle` | 胜负产生 | 结算完成 | 基地血量为 0 → 直接判胜负；计时到 → **比剩余基地血量** |
| `Result` | 结算完成 | 玩家重开 / 退出 | — |

**关键约定**

- **无波次**：节奏由四个独立 tick 驱动（收入 1s / 产出按各建筑 interval / 敌方档位 60s / 技能冷却）
- **单位不因波末清除**：靠 ① 中路交战 ② 基地防御火力 ③ 外圈建筑被摧毁 三者共同消耗，防止撞单位上限
- **精炼厂冻结是全局收入状态**（`frozen_until` 时间戳），不是每厂一个计时器 → 简单且不会互相打架
- **建筑可被摧毁**：建筑需要有血量与受击判定；摧毁后**槽位释放、金币不返还**（D11），可重建

---

## 3. 事件清单（L1 → L2 的唯一接口）

| 事件 | 载荷 | 消费方 |
| --- | --- | --- |
| `OnRunStart` | run_seed | HUD |
| `OnGoldChanged` | gold, income_per_s, frozen_until | HUD |
| `OnSlotClicked` | slot_id, zone(inner/outer) | BuildUI |
| `OnBuildRequested` | slot_id, building_def_id | L1 |
| `OnBuildCompleted` | slot_id, building_id, def_id | HUD, View |
| `OnBuildRejected` | slot_id, reason(占用/缺钱/缺科技) | BuildUI |
| `OnBuildingDamaged` | building_id, hp_left | View |
| `OnBuildingDestroyed` | building_id, slot_id | HUD, View |
| `OnUnitSpawned` | unit_id, def_id, tier, **faction_id** | View |
| `OnUnitKilled` | unit_id, **faction_id** | — |
| `OnUnitArrived` | unit_id, **target_faction_id** | HUD |
| `OnBaseDamaged` | **faction_id**, hp_left | HUD |
| `OnTierUp` | **faction_id**, tier | HUD |
| `OnSkillReady` / `OnSkillUsed` | skill_id | SkillUI |
| `OnFreezeChanged` | frozen_until | HUD |
| `OnRunEnd` | result(win/lose), duration_s, base_hp_left | ResultUI, RankAdapter |

---

## 4. 数据模型

```
RunState {
  seed: int
  faction_id: string            # 开局所选派系（D-R9），整局不可变更
  commander_id: string          # 开局所选指挥官（D-R10）→ 作为「职业」赋予玩家（D-R11）
  elapsed_s: float              # 局内计时（0..720）
  phase: enum                   # RunInit|Battle|Settle|Result
  gold: float
  income_per_s: float           # income_base + Σ 已生效精炼厂加成
  frozen_until: float           # 全局收入冻结到期时间（0 = 未冻结）
  slots: list<Slot>             # 12 个：内圈 6 + 外圈 6
  tech_unlocked: set<tech_id>   # 解锁 T2 / T3
  skill_cd: map<skill_id, float>
  bases: map<faction_id, BaseState>   # 对称：每阵营一个基地（v1 只有 A/B 两方）
  tier: map<faction_id, int>    # 每阵营的强度档位（v1 只有 B 阵营升档）
  result: enum|null             # win | lose | timeout
}

Slot     { slot_id, zone: inner|outer, building_id|null }
Building { building_id, def_id, slot_id, hp, max_hp, spawn_timer }
Unit     { unit_id, def_id, tier, faction_id, hp, atk, path_index, state: march|fight|attack_base }
BaseState{ faction_id, hp, max_hp, defense_cd }
FactionRuntime { faction_id, faction_def_id, commander_id|null, gold, income_per_s,
                 frozen_until, slots[], driver: ai|player }   # ← 对称：联机时两方各一份
Skill    { id, name, cd_s, effect: list<{op, params}> }
```

**关键设计**（三条，都是为了不出同步 bug）：

1. **建筑与槽位分离**：`Slot` 只保存占用关系，`Building` 保存血量与产出计时 → 建筑被摧毁时清掉二者即可，**槽位天然可重建**（D11）
2. **全局冻结用一个 `frozen_until` 时间戳**，不是每厂一个计时器 → 多厂叠加不会互相打架
3. **单位不存"所属建筑"**：产出即独立 → 建筑被摧毁时单位不会连带失效

---

## 5. 配置表 schema（L0）

| 表 | 字段 | 说明 |
| --- | --- | --- |
| `balance.csv` | 键值对全集 | §数值模型 **v0.2**（沙漠风暴式拉锯战）的全部变量 |
| `factions.csv` | `id, name, icon, unit_pool[], enemy_faction_id` | **派系**（D-R9）：兵种池（外观）+ `enemy_faction_id` 决定对手（F1：取敌对一方） |
| `faction_modifiers.csv` | `faction_id, key, op(mul/add), value` | **派系修正表**（F3）：对 `balance.csv` 任意键的乘/加修正 → **数值表不分叉**，逻辑只需要一条 `get_param(key, faction_id, commander_id)` 路径 |
| `passives.csv`（同 `commander_modifiers` 语义） | `passive_id, key, op(mul/add), value` | **指挥官被动修正**：与派系修正**同一条读取路径**叠加 → 被动不写逻辑 |
| `buildings.csv` | `id, name, asset, cost, hp, spawn_interval, spawn_unit_id, unlock_condition, zone_allowed` | **4 种**（D7）：兵营 T1/T2/T3 + 精炼厂；`unlock_condition` = **累计收入里程碑**（D13：500 → T2、1500 → T3） |
| `units.csv` | `id, name, asset, faction_id, tier, hp, atk, atk_interval, move_speed_mul, base_damage` | 单位定义；**我方与敌方共用同一张表**（`faction_id` 区分） |
| `enemy_tiers.csv` | `tier, spawn_interval, unit_id, strength_mul` | 12 档敌方强度曲线 |
| `commanders.csv` | `id, name, icon, class_id, active_skill_id, passive_id` | **指挥官**（D-R10/D-R11）：**1 主动 + 1 被动**；**全局池**（F5）；**`class_id` = 绑定到玩家的职业**；⚠️ **v1 六个职业共用同一个镜头模板**（F10），将来想分化只改配置 |
| `active_skills.csv` | `id, name, icon, cd_s, effect[], params` | **主动技能池**（v1 = 6 个，各带冷却） |
| `passives.csv` | `id, name, desc, modifiers[]` | **被动池**（v1 = 6 组）—— 本质是**参数修正**，与 `faction_modifiers` 同一套机制 |
| `slots.csv` | `slot_id, zone, position_preset_index` | 槽位 ↔ **预设点索引**（内圈 6 / 外圈 6） |
| `paths.csv` | `path_id, waypoint_preset_indices[]` | 中路路径（引用预设点，≤50 路点/条） |

> 表格式建议 **CSV**（策划可编辑、可 diff）；运行时转 JSON。**不把数值写进逻辑。**

---

## 6. 平台适配层（决定能否移植）

| 接口 | 职责 | 千星奇域 | Steam | 移动端 |
| --- | --- | --- | --- | --- |
| `InputAdapter` | 输出一个移动向量 | 角色移动 | 键鼠/手柄 | 虚拟摇杆（触屏） |
| `SaveAdapter` | 局外持久化（预留） | 局内存档 | 本地文件/Steam Cloud | 本地/云存档 |
| `RankAdapter` | 写排行榜 | 官方外围系统排行榜 | Steam Leaderboards | Google Play / Game Center / 自建 |
| `AchievementAdapter` | 成就（首图不做，预留） | 官方成就 | Steam Achievements | 平台成就 |
| `Clock` | 时间源 | 引擎计时器 | 系统时间 | 系统时间 |
| `RNG` | 确定性随机（种子） | 平台随机节点 | 自实现 PRNG | 自实现 PRNG |

**输入抽象是移动端的关键**：本设计玩家**只需一个移动向量**（无攻击/无技能按钮）→ 触屏只需一个虚拟摇杆，**这是"只走位"玩法在移动端的最大红利**，移植时不需要重做操作。

---

## 7. 移植差异矩阵

| 维度 | 千星奇域（UGC） | Steam（独立发行） | 移动端 |
| --- | --- | --- | --- |
| 🔴 **合规** | 受《奇匠创作守则》约束（摘录见 `rules/compliance.md`） | **只能用通用层设计重新实现**；不得导出搬运奇域内容、不得使用官方素材 | 同 Steam |
| 平台约束 | 官方编辑器能力上限（见实现层文档） | 几乎无上限 | 性能与包体受限 |
| 画面基准 | 俯视 2.5D，自带资产 | 可提升美术 | 需 LOD/贴图压缩 |
| 单位规模 | 60 怪 + 7 随从 + 特效 | 可放大 | **需下调或减特效** |
| 排行榜 | 官方外围系统（上限 3 个、前 1000 名） | Steam Leaderboards（可多榜） | 平台榜或自建 |
| 收益方式 | 灵感激励计划（一号创作票券） | 买断 / 愿望单转化 | 免费 + 广告 / IAP |
| 留存手段 | 平台推荐位 + 奇匠订阅 | **需 meta 进度**（见 §9） | **需 meta 进度 + 日常** |
| 语言 | 官方多语言文本组件 | 需自建 i18n | 需自建 i18n |

> ⚠️ **注意**：平台上架后"平台激励"消失，**留存要靠设计本身**。当前设计**没有跨局成长（meta 进度）** → 独立发行前必须补（§9 Q25）。

### 🔴 移植的合规红线（2026.9.25《奇匠创作守则》到手后确认）

移植**不是「导出」，而是「重新实现」**：

| 能带走的 | 不能带走的 |
| --- | --- |
| ✅ 本文件 + `balance-model.md`（我们自己的**抽象设计**：架构、数值、规则） | 🚫 千星沙箱的**奇域内容**（`.gil` / `.gia`、存档、元件）—— 守则第三条（一）禁止导出搬运至第三方平台 |
| | 🚫 **任何官方素材**（模型 / 贴图 / 音效 / UI）—— 守则第三条（二）禁止在非本服务场景使用 |
| | 🚫 官方 IP 元素、名称、角色形象 |

⚠️ 条文原文是「未经**许可**不得」→ 存在许可路径，**真要做移植应先向官方确认**。
📌 这也解释了为什么要把架构与数值做成通用层：**抽象设计可以走，具体内容与素材不能走。**

---

## 8. 性能预算（通用，按最低目标平台取）

| 项 | 预算 | 依据 |
| --- | --- | --- |
| **同屏单位总数**（双方合计） | **≤ 120** | 本玩法单位**持续累积**（不像波次玩法会清场）→ 这是最需要盯的一条 |
| 建筑 | ≤ 12（内圈 6 + 外圈 6） | 槽位硬上限 |
| 基地 | 2 | 双方各一 |
| 掉落的单位（到达基地后持续攻击） | ≤ 40 | 靠基地防御火力与中路交战消耗 |
| 单次 AOE 命中 | ≤ 20 实体 | 千星奇域硬限；**移动端也按此设计更安全** |
| 特效同屏 | ≤ 10 | — |
| 客户端 UI 控件 | 面板 ≤ 60 个（含列表项复用） | 客户端 Lua 侧预算，见 `desert-strike.md` 验证清单第 6 项 |

---

## 9. 已知缺口与待定

| # | 缺口 | 影响 | 何时必须解决 |
| --- | --- | --- | --- |
| **Q25** | **要不要跨局 meta 进度**（永久解锁天赋/随从/皮肤） | 千星奇域有排行榜与推荐位可以不带 meta；**Steam/移动端没有 meta 会严重伤留存** | 首发可先不做；**移植前必须定** |
| Q26 | 联机（当前明确不做） | 若将来做，战斗结算需服务端权威，架构要预留 | 移植后 |
| Q27 | 变现方式（买断/广告/IAP） | 会影响 UI 布局与波间节奏（例如广告插在波间） | 移植前 |
| Q28 | i18n 方案 | 文本若散落在逻辑里，后期抽不出来 | **从现在开始：所有文本走 key，不写死在逻辑** |
| Q29 | 配置表格式（CSV/JSON/YAML）与版本管理 | 影响策划协作与 diff | 动手实现前 |
