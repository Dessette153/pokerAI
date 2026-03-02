"""
app/engine/cards.py - Card and Deck representations
"""
from __future__ import annotations
import random
from typing import List

# Rank constants: 2-14 (A=14)
RANK_STRS = {2: '2', 3: '3', 4: '4', 5: '5', 6: '6', 7: '7',
             8: '8', 9: '9', 10: 'T', 11: 'J', 12: 'Q', 13: 'K', 14: 'A'}
RANK_MAP = {v: k for k, v in RANK_STRS.items()}
SUIT_STRS = {0: 'c', 1: 'd', 2: 'h', 3: 's'}
SUIT_MAP = {'c': 0, 'd': 1, 'h': 2, 's': 3}


class Card:
    __slots__ = ('rank', 'suit')

    def __init__(self, rank: int, suit: int):
        # rank: 2-14, suit: 0=clubs,1=diamonds,2=hearts,3=spades
        self.rank = rank
        self.suit = suit

    @classmethod
    def from_str(cls, s: str) -> 'Card':
        """Parse '2c', 'Ah', 'Ts', 'Kd' etc."""
        s = s.strip()
        rank_str = s[:-1].upper()
        suit_str = s[-1].lower()
        rank_str = rank_str if rank_str not in ('T',) else 'T'
        rank = RANK_MAP.get(rank_str.upper())
        if rank is None:
            # try numeric
            rank = int(rank_str)
        suit = SUIT_MAP[suit_str]
        return cls(rank, suit)

    def __str__(self) -> str:
        return f"{RANK_STRS[self.rank]}{SUIT_STRS[self.suit]}"

    def __repr__(self) -> str:
        return f"Card({self!s})"

    def __eq__(self, other) -> bool:
        return isinstance(other, Card) and self.rank == other.rank and self.suit == other.suit

    def __hash__(self) -> int:
        return self.rank * 4 + self.suit

    def to_dict(self) -> dict:
        return {'rank': self.rank, 'suit': self.suit, 'str': str(self)}


class Deck:
    def __init__(self):
        self._cards: List[Card] = [
            Card(rank, suit)
            for rank in range(2, 15)
            for suit in range(4)
        ]
        self._dealt: set = set()

    def shuffle(self) -> None:
        random.shuffle(self._cards)
        self._dealt = set()

    def deal(self, n: int = 1) -> List[Card]:
        result = []
        for card in self._cards:
            if card not in self._dealt:
                self._dealt.add(card)
                result.append(card)
                if len(result) == n:
                    break
        if len(result) < n:
            raise ValueError(f"Not enough cards in deck (need {n}, have {52 - len(self._dealt)})")
        return result

    def deal_one(self) -> Card:
        return self.deal(1)[0]

    def remove(self, cards: List[Card]) -> None:
        for c in cards:
            self._dealt.add(c)

    @property
    def remaining(self) -> List[Card]:
        return [c for c in self._cards if c not in self._dealt]

    def __len__(self) -> int:
        return 52 - len(self._dealt)
