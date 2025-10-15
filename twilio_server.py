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
else:
    logger.info(f"✅ TWILIO_STREAM_URL: {TWILIO_STREAM_URL}")

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

    xml_response = response.to_xml()
    logger.debug(f"Responding with TwiML:\n{xml_response}")
    return Response(content=xml_response, media_type="application/xml")


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
            add_wav_header=True,  # 👈 important for Twilio
            vad_analyzer=SileroVADAnalyzer(),
        )
    }

    try:
        transport = await create_transport(runner_args, transport_params)
    except Exception as e:
        logger.exception(f"❌ Failed to create transport: {e}")
        await websocket.close()
        return

    # Run Pipecat bot asynchronously
    bot_task = asyncio.create_task(run_bot(transport=transport, runner_args=runner_args))

    try:
        await bot_task  # Wait for bot completion
    except asyncio.CancelledError:
        logger.warning("🛑 Bot task cancelled.")
    except Exception as e:
        logger.exception(f"💥 Error while running bot: {e}")
    finally:
        # Ensure the WebSocket is closed properly
        if websocket.client_state.name != "DISCONNECTED":
            try:
                await websocket.close()
            except Exception as e:
                logger.warning(f"⚠️ Error closing websocket: {e}")
        logger.info("🔌 WebSocket connection closed and cleaned up.")
