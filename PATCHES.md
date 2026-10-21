# 本地补丁

`ziyou/patches` 分支 = 上游稳定版 + 下面这些补丁，一个补丁一个 commit。上游修好后删掉对应的 commit。

| 补丁 | 现象 | 上游 |
|---|---|---|
| fix(feishu): reply in thread when a topic send has no reply target | 飞书话题里，后台任务完成通知、定时任务投递、排队的后续回复没有回复对象，发送时报 `99992402 field validation failed`，回复丢失 | [#78975](https://github.com/NousResearch/hermes-agent/issues/78975)；PR #94306、#104747、#109803 都没合 |

## 当前基线

- 上游 tag：`v0.22.2`（`d923a5eb48`）
- 运行目录 `~/.local/share/hermes-stable/app` 从 2026-10-21 起停在本地分支 `ziyou/patches` 上，跟踪远程 `fork`（`origin` 仍是 NousResearch）。
- 部署：在运行目录 `git fetch fork && git checkout -B ziyou/patches fork/ziyou/patches`，再执行 `launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway-vediotutor-buddy`。
- 不要再跑 `hermes update`：它会把代码切回官方版本，补丁就失效了。回滚：切回上游 tag 对应的提交再重启。

## 升级

```bash
git fetch upstream --tags
git rebase --onto <新 tag> <旧 tag> ziyou/patches   # 冲突时逐个解决；上游已修好的补丁直接丢掉
```

然后跑测试，推到 fork，更新上面的「当前基线」，再按上面的部署步骤切换运行目录、重启网关。

## 测试

`uv pip install --target <临时目录> pytest==9.1.1 pytest-asyncio==1.3.0`，然后用网关的 Python 环境跑：

```bash
PYTHONPATH=<临时目录>:$PWD <网关 venv>/bin/python -m pytest tests/gateway/test_feishu*.py tests/gateway/test_stream_consumer_thread_routing.py -q
```
