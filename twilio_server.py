import os
import asyncio
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Connect
from loguru import logger

# Import your existing bot setup
from chatbot import run_bot
from pipecat.runner.types import RunnerArguments

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

    return Response(content=str(response), media_type="application/xml")


@app.websocket("/stream")
async def websocket_stream(websocket: WebSocket):
    """
    Handles bidirectional WebSocket audio streaming between Twilio and Pipecat bot.
    """
    await websocket.accept()
    logger.info("🔊 Twilio WebSocket connected")

    # Create RunnerArguments for Pipecat bot
    runner_args = RunnerArguments(transport="webrtc", handle_sigint=False)

    # Run Pipecat bot asynchronously
    bot_task = asyncio.create_task(run_bot(transport=None, runner_args=runner_args))

    try:
        while True:
            data = await websocket.receive_text()
            logger.debug(f"Received data from Twilio: {data}")
            # Forward this data to your Pipecat bot if needed
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await websocket.close()
        logger.info("🔌 WebSocket closed")
        bot_task.cancel()
