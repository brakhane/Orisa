import logging
import trio


logging.basicConfig()

logger = logging.getLogger("foo")
logger.setLevel(logging.DEBUG)


send, recv = trio.open_memory_channel(5)

async def foo():
    logger.info("foo")
    print("asd")


    await send.send("x")
    async for i in recv:
        logger.info("%s", i)
        try:
            with trio.move_on_after(1):
                await bar()
        except Exception:
            logger.exception("foo")
        print("XXX")
        await send.send("x")

async def bar():
    await trio.sleep(5)

trio.run(foo)