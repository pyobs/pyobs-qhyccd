import asyncio

from .qhyccddriver import QHYCCDDriver, Control, set_log_level  # type: ignore


async def gui():
    print("gui")
    print("aa")


def main():
    asyncio.run(gui())