from autorop import PwnState, arutil, constants
from pwn import context, ROP, log, align, pack
from typing import List


def align_call(rop: ROP, func: str, args: List[int]) -> ROP:
    """Align the stack prior to making a rop call to it.

    Arguments:
        rop: Current rop chain, just before making the call to the function.
        func: Symbol name of the function to call.
        args: Arguments to pass to the function.

    Returns:
        Reference to the mutated ``rop``, performing the function call
        ensuring the stack is aligned.
    """
    # we will build a fake chain to determine when the function is called
    # relative to other gadgets
    predict_rop = ROP(rop.elfs)
    predict_rop.call(func, args)
    log.debug("Making prediction rop chain for stack alignment purposes...")
    log.debug(predict_rop.dump())
    # search for offset of function address in payload
    index: int = predict_rop.chain().index(pack(rop.resolve(func)))
    log.debug(f"Offset till function call: {index}")

    # ensure that call is stack-aligned,
    # assuming that we are already within a function (with the alignment invariant)
    # by padding up to the call
    current_length = len(rop.chain()) + index
    alignment = (
        align(constants.STACK_ALIGNMENT, current_length) + constants.STACK_ALIGNMENT
    ) // context.bytes - 1
    # prevent excessive aligning
    alignment %= constants.STACK_ALIGNMENT // context.bytes
    arutil.align_rop(rop, len(rop.chain()) // context.bytes + alignment)

    # actually perform the function call
    rop.call(func, args)

    return rop
