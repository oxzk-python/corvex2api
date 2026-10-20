"""账号模型与进程内存池."""

from __future__ import annotations

import time
from dataclasses import dataclass

from infra.pricing import INITIAL_BALANCE_USD

ACTIVE = "active"
EXHAUSTED = "exhausted"
RATE_LIMITED = "rate_limited"


@dataclass
class Account:
    """一条账号记录, 状态决定是否参与选号."""

    id: str
    key: str
    status: str = ACTIVE
    until: float = 0.0
    initial_balance: float = INITIAL_BALANCE_USD

    def healthy(self) -> bool:
        """剔除后不可用, 429 冷却到期自动恢复."""
        if self.status == EXHAUSTED:
            return False
        if self.status == RATE_LIMITED:
            return self.until <= time.time()
        return True


class AccountPool:
    """内存账号池, 每次请求前 reload 刷新, round-robin 选号."""

    def __init__(self) -> None:
        """持有空池与轮转游标."""
        self._accounts: dict[str, Account] = {}
        self._cursor = 0

    def reload(self, accounts: list[Account]) -> None:
        """用 Redis 最新数据整体替换池内容."""
        self._accounts = {account.id: account for account in accounts}

    def all(self) -> list[Account]:
        """返回池内全部账号快照."""
        return list(self._accounts.values())

    def get(self, account_id: str) -> Account | None:
        """按 ID 读取账号."""
        return self._accounts.get(account_id)

    def upsert(self, account: Account) -> None:
        """写入或覆盖单个账号, 供导入后立即可用."""
        self._accounts[account.id] = account

    def remove(self, account_id: str) -> None:
        """剔除单个账号."""
        self._accounts.pop(account_id, None)

    def mark(self, account_id: str, status: str, until: float = 0.0) -> None:
        """更新账号状态, 不中断在途请求."""
        account = self._accounts.get(account_id)
        if account is not None:
            account.status = status
            account.until = until

    def pick(self, tried: set[str] | None = None) -> Account | None:
        """round-robin 挑一个可用账号, 跳过本次请求已试过的."""
        skip = tried if tried is not None else set()
        candidates = [a for a in self._accounts.values() if a.id not in skip and a.healthy()]
        if not candidates:
            return None
        self._cursor = (self._cursor + 1) % len(candidates)
        return candidates[self._cursor]

    def snapshot(self) -> dict[str, int]:
        """输出各状态计数与当前可用数."""
        counts = {
            "total": len(self._accounts),
            "available": 0,
            "active": 0,
            "exhausted": 0,
            "rate_limited": 0,
        }
        for account in self._accounts.values():
            counts[account.status] = counts.get(account.status, 0) + 1
            if account.healthy():
                counts["available"] += 1
        return counts
