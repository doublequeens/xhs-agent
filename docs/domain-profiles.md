# Domain 与内容策略

项目用一套 LangGraph 工作流支持三个 domain，但账号当前的正式主线是美容护肤：日常运行推荐 `beauty`，尤其是 `beauty/skincare`。`wellness` 与 `healthy_lifestyle` 只是代码支持的扩展能力，不应被理解为当前账号的同等内容定位。

## Domain 与 subdomain

| Domain | 实际 subdomain | 当前说明 |
| --- | --- | --- |
| `beauty` | `skincare`、`haircare`、`bodycare`、`makeup_basics` | 正式主线；优先使用 `skincare` |
| `wellness` | `sleep`、`stress_management`、`daily_routine`、`recovery` | 技术支持的生活方式扩展 |
| `healthy_lifestyle` | `nutrition_basics`、`exercise`、`hydration`、`sedentary_habits`、`daily_habits` | 技术支持的健康生活方式扩展 |

Profile 定义在 `src/domain/profiles.py`，并按版本管理。Profile 负责 subdomain 词表、禁用主题和 claims、免责声明、标签种子、视觉指导以及证据来源 allowlist。

## 运行时选择

已知 domain 时显式传入；否则 router 会根据 `--focus_keyword` 推断 domain/subdomain。显式 domain 优先于关键词推断；低置信度时图会暂停，要求确认 domain 和 subdomain。

```bash
python main.py --domain beauty --subdomain skincare --focus_keyword "夏季防晒"
python main.py --focus_keyword "睡前作息"
python main.py --domain healthy_lifestyle --subdomain sedentary_habits --focus_keyword "久坐办公"
```

不支持的 domain 或与 profile 不匹配的 subdomain 会在记忆检索前被 CLI 拒绝。账号要保持单一人群和稳定审美时，应优先使用 beauty/skincare，而不是在三个 domain 之间随机切换。

## 证据与风险

需要事实检索时，配置 Tavily key（不要把真实 key 写入文档或提交仓库）：

```bash
export TAVILY_API_KEY="your-key"
```

默认证据来源 allowlist 为：

```text
who.int
nih.gov
cdc.gov
nhs.uk
nhc.gov.cn
chinacdc.cn
```

中风险或 profile 标记为 `basic_science` 的主题会触发证据要求。要求证据但检索失败，或没有 allowlist 来源时，工作流会在 outline 之前停止。搜索摘要只作为未验证材料，不能直接升级成医疗事实或个体化建议。

所有 domain 都禁止疾病诊断、治疗方案、药物建议、检查指标解读和个体化处方，也禁止“保证有效”“根治”“永久改善”“立即见效”“替代治疗”等保证性 claims。健康相关内容还必须保留 profile 的一般生活方式免责声明。

## 审核、记忆与隔离

人工审核包包含 domain 元数据、风险标记、命中的策略规则、最终策略问题和证据项。只有人工明确批准、通过 R2 合规和 Final Guard 的包，才能到 `content_writer`；拒绝、缺字段、治疗/药物/剂量建议或保证性结果都不能写入结构化或向量记忆。

结构化记录和检索按 domain/subdomain 分区；性能分析可通过 `XHSMemoryManager.get_performance_by_domain()` 查看。不要把一个 domain 的历史内容当成另一个 domain 的默认素材或受众依据。

## 旧数据迁移

`XHSMemoryManager.init_db()` 执行幂等的结构化记忆迁移。缺少 domain 元数据的旧记录会按兼容默认值回填：

```text
domain=beauty
subdomain=skincare
profile_version=legacy-v1
risk_level=low
```

首次记忆检索会补齐向量元数据，并在成功后记录 `vector_domain_backfill_v1` 事件。空数据库不会标记为已迁移，以便之后导入旧数据。缺少 `domain_context` 的旧 LangGraph checkpoint 在恢复时以 beauty/skincare 兼容 profile 补齐，并发出一次警告。
