import os
import asyncio
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Connect
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.runner.utils import create_transport

# Import your existing bot setup
from chatbot import run_bot
from pipecat.runner.types import WebSocketRunnerArguments
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams

app = FastAPI()

# Get the Twilio WebSocket URL from environment variable
TWILIO_STREAM_URL = os.environ.get("TWILIO_STREAM_URL")
if not TWILIO_STREAM_URL:
    logger.error("TWILIO_STREAM_URL is not set! Please define it in environment variables.")

@app.post("/voice")
async def voice_webhook(request: Request):
    """
    Endpoint called by Twilio when a call starts.
    Responds with TwiML instructing Twilio to open a WebSocket to /stream.
    """
    logger.info("📞 Incoming call received from Twilio")

    response = VoiceResponse()
    connect = Connect()

    # Use environment variable for stream URL
    connect.stream(url=TWILIO_STREAM_URL)
    response.append(connect)

    return Response(content=response.to_xml(), media_type="application/xml")


@app.websocket("/stream")
async def websocket_stream(websocket: WebSocket):
    """
    Handles bidirectional WebSocket audio streaming between Twilio and Pipecat bot.
    """
    await websocket.accept()
    logger.info("🔊 Twilio WebSocket connected")

    # Create RunnerArguments for Pipecat bot
    runner_args = WebSocketRunnerArguments(websocket=websocket)

    transport_params = {
        "twilio": lambda: FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
        )
    }

    transport = await create_transport(runner_args, transport_params)

    # Run Pipecat bot asynchronously
    bot_task = asyncio.create_task(run_bot(transport=transport, runner_args=runner_args))

    try:
        while True:
            await asyncio.sleep(5)
            if websocket.application_state != "CONNECTED":
                break
            try:
                await websocket.send_text("ping")
            except Exception:
                break
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        try:
            if websocket.application_state == "CONNECTED":
                await websocket.close()
        except Exception as e:
            logger.warning(f"WebSocket already closed: {e}")
        logger.info("🔌 WebSocket cleanup complete")
        bot_task.cancel()
