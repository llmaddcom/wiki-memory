"""按 space 串行化"评估→LLM→落库"写入口的进程内锁。

固化与 delete-by-ref 都是先读影响面、再做 LLM 调用、最后写库；两个请求
并发时，后落库者引用的 source 可能已被先落库者硬删（evidence 外键违规、
整体回滚 500）。上游删除多个会话时逐会话触发连带遗忘，正是这种并发。

服务是单进程部署（main.py 单 worker、sync 路由跑线程池），进程内互斥
即可覆盖全部写入口；若来日多进程/多实例部署，须换成数据库级锁
（如 pg advisory lock）。
"""

import threading

_guard = threading.Lock()
_locks: dict[int, threading.Lock] = {}


def space_write_lock(space_id: int) -> threading.Lock:
    """同一 space 的写入口（consolidate、delete-by-ref）共用一把互斥锁。"""
    with _guard:
        return _locks.setdefault(space_id, threading.Lock())
