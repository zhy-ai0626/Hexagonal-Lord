"""军队：7 个槽位，每个槽位一支部队（兵种 + 数量）。英雄、城镇守军、野怪都用它。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from .data import CreatureType

ARMY_SLOTS = 7


@dataclass
class Stack:
    type: CreatureType
    count: int

    @property
    def value(self) -> float:
        return self.type.value * self.count

    def __repr__(self) -> str:
        return f"{self.type.name}×{self.count}"


class Army:
    def __init__(self):
        self.slots: list[Stack | None] = [None] * ARMY_SLOTS

    # ---------- 查询 ----------
    def stacks(self) -> Iterator[Stack]:
        for s in self.slots:
            if s is not None and s.count > 0:
                yield s

    def is_empty(self) -> bool:
        return not any(True for _ in self.stacks())

    def total_value(self) -> float:
        return sum(s.value for s in self.stacks())

    def total_count(self) -> int:
        return sum(s.count for s in self.stacks())

    def min_speed(self) -> int:
        speeds = [s.type.speed for s in self.stacks()]
        return min(speeds) if speeds else 0

    def count_of(self, ctype: CreatureType) -> int:
        return sum(s.count for s in self.stacks() if s.type is ctype or s.type.id == ctype.id)

    def free_slots(self) -> int:
        return sum(1 for s in self.slots if s is None or s.count <= 0)

    def can_add(self, ctype: CreatureType) -> bool:
        return any(s.type.id == ctype.id for s in self.stacks()) or self.free_slots() > 0

    # ---------- 修改 ----------
    def add(self, ctype: CreatureType, count: int) -> bool:
        """加入部队；同兵种自动合并。放不下返回 False。"""
        if count <= 0:
            return True
        for s in self.stacks():
            if s.type.id == ctype.id:
                s.count += count
                return True
        for i, s in enumerate(self.slots):
            if s is None or s.count <= 0:
                self.slots[i] = Stack(ctype, count)
                return True
        return False

    def remove_dead(self) -> None:
        for i, s in enumerate(self.slots):
            if s is not None and s.count <= 0:
                self.slots[i] = None

    def clear(self) -> None:
        self.slots = [None] * ARMY_SLOTS

    def swap(self, i: int, j: int) -> None:
        self.slots[i], self.slots[j] = self.slots[j], self.slots[i]

    def merge_into(self, other: "Army") -> None:
        """把自己的所有部队尽量并入 other（放不下的留在自己这里）。"""
        for i, s in enumerate(self.slots):
            if s is not None and s.count > 0 and other.add(s.type, s.count):
                self.slots[i] = None

    def copy(self) -> "Army":
        a = Army()
        a.slots = [Stack(s.type, s.count) if s else None for s in self.slots]
        return a

    def describe(self) -> str:
        return "，".join(f"{s.type.name}×{s.count}" for s in self.stacks()) or "（空）"


def transfer_stack(src: Army, i: int, dst: Army, j: int) -> None:
    """把 src 的第 i 槽移到 dst 的第 j 槽：空位直接放，同兵种合并，不同兵种交换。"""
    a, b = src.slots[i], dst.slots[j]
    if a is None:
        return
    if b is None:
        dst.slots[j], src.slots[i] = a, None
    elif a.type.id == b.type.id:
        b.count += a.count
        src.slots[i] = None
    else:
        dst.slots[j], src.slots[i] = a, b


def split_stack(src: Army, i: int, dst: Army, j: int, n: int) -> bool:
    """把 src 第 i 槽分出 n 个到 dst 第 j 槽（j 必须是空位或同兵种）。"""
    a = src.slots[i]
    if a is None or n <= 0 or n >= a.count:
        return False
    b = dst.slots[j]
    if b is None:
        dst.slots[j] = Stack(a.type, n)
    elif b.type.id == a.type.id:
        b.count += n
    else:
        return False
    a.count -= n
    return True
