# 项目交接说明 (HANDOVER)

- **当前进度**：双端解密、防撤回就绪；文件与收藏支持全量加载(含进度条)、来源检索与隐藏；修复macOS目录选择崩溃，前端已编译。
- **下一步**：增强本地大图与视频深度匹配归档；调优语音批量转写队列。
- **关键决策**：100%纯本地只读，剔除外部云端代理(wxcdn)，严禁发包防封号；macOS改用osascript杜绝Tkinter线程崩溃。
- **踩过的坑**：macOS子线程调Tkinter抛`NSInternalInconsistencyException`闪退；复用路由函数需解包`Query()`。
- **重要文件**：`main.py`(入口)、`src/wechat_decrypt_tool/routers/{files,favorites,system}.py`、`frontend/components/RecordExportDialog.vue`。
- **新AI第一步**：运行`.venv/bin/python main.py`，访问`http://127.0.0.1:10392`验证。
