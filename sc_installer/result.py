# Copyright (C) 2026  wormt <209373679+wormt@users.noreply.github.com>
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Minimal Result type for error handling. goated"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn, TypeVar

T = TypeVar("T")
U = TypeVar("U")


@dataclass(frozen=True)
class Ok[T]:
    value: T

    @property
    def is_ok(self) -> bool:
        return True

    def map(self, fn: Callable[[T], U]) -> Result[U]:
        return Ok(fn(self.value))

    def bind(self, fn: Callable[[T], Result[U]]) -> Result[U]:
        return fn(self.value)

    def unwrap(self) -> T:
        return self.value

    def unwrap_or(self, _default: U) -> T | U:
        return self.value

    def expect(self, _msg: str) -> T:
        return self.value


@dataclass(frozen=True)
class Err:
    error: str

    @property
    def is_ok(self) -> bool:
        return False

    def map(self, _fn: Callable[[object], U]) -> Result[U]:
        return Err(self.error)

    def bind(self, _fn: Callable[[object], Result[U]]) -> Result[U]:
        return Err(self.error)

    def unwrap(self) -> NoReturn:
        raise RuntimeError(f"unwrap on Err: {self.error}")

    def unwrap_or(self, default: U) -> U:
        return default

    def expect(self, msg: str) -> NoReturn:
        raise RuntimeError(f"{msg}: {self.error}")


Result = Ok[T] | Err

type LogFn = Callable[..., None]


def collect[T](results: list[Result[T]]) -> Result[list[T]]:
    values: list[T] = []
    for r in results:
        match r:
            case Ok(v):
                values.append(v)
            case Err() as e:
                return e
    return Ok(values)
