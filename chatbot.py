"""Pipecat Quickstart Example.

The example runs a simple voice AI bot that you can connect to using your
browser and speak with it. You can also deploy this bot to Pipecat Cloud.

Required AI services:
- Deepgram (Speech-to-Text)
- OpenAI (LLM)
- Cartesia (Text-to-Speech)

Run the bot using:

    uv run chatbot.py
"""

import os
import random
import string
import asyncio

import uuid
from dotenv import load_dotenv
from loguru import logger

print("🚀 Starting Pipecat bot...")
print("⏳ Loading models and imports (20 seconds, first run only)\n")

logger.info("Loading Local Smart Turn Analyzer V3...")
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3

logger.info("✅ Local Smart Turn Analyzer V3 loaded")
logger.info("Loading Silero VAD model...")
from pipecat.audio.vad.silero import SileroVADAnalyzer

logger.info("✅ Silero VAD model loaded")

from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMRunFrame

logger.info("Loading pipeline components...")
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.frameworks.rtvi import RTVIConfig, RTVIObserver, RTVIProcessor
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from supabase import create_client, Client
from pipecat.processors.transcript_processor import TranscriptProcessor

logger.info("✅ All components loaded successfully!")

load_dotenv(override=True)

# --- Supabase setup ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

SESSION_ID = str(uuid.uuid4())  # Unique session ID per conversation

# Create a single transcript processor instance
transcript = TranscriptProcessor()

@transcript.event_handler("on_transcript_update")
async def handle_transcript_update(processor, frame):
    # Each message contains role (user/assistant), content, and timestamp
    logger.debug('We are here!')
    for message in frame.messages:
        print(f"[{message.timestamp}] {message.role}: {message.content}")
        # Save to Supabase
        supabase.table('conversation_logs').insert({
            'role': message.role,
            'message': message.content,
            'timestamp': message.timestamp,
            'session_id': SESSION_ID
        }).execute()

def generate_claim_number():
    """Generate a 10-character alphanumeric claim number containing '000'."""
    while True:
        s = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
        insert_pos = random.randint(0, 7)
        s = s[:insert_pos] + "000" + s[insert_pos + 3:]
        if "000" in s:
            return s


async def scripted_conversation(task, messages, context, context_aggregator, claim_number):
    """
    Drive the assistant (bot) through a structured, interactive conversation.
    Here, the bot plays the role of a customer calling about a claim.
    """

    conversation_steps = [
        {"prompt": "I need information about a claim."},
        {"prompt": f"The claim number is {claim_number}"},
        {"prompt": "When was the claim submitted?"},
        {"prompt": "What is the status?"},
    ]

    step_index = 0
    total_steps = len(conversation_steps)

    async def next_bot_line():
        nonlocal step_index
        if step_index < total_steps:
            msg = conversation_steps[step_index]["prompt"]
            logger.info(f"Bot says: {msg}")
            messages.append({"role": "assistant", "content": msg})
            await task.queue_frames([LLMRunFrame()])
            step_index += 1
        if step_index >= total_steps:
            final_msg = "Thanks! That covers everything I needed."
            messages.append({"role": "assistant", "content": final_msg})
            await task.queue_frames([LLMRunFrame()])

    # Start conversation after connection
    await next_bot_line()

    # Listen for user turns via the aggregator
    @context_aggregator.user().event_handler("on_message")
    async def on_user_message(processor, message):
        """Triggered each time the user responds."""
        logger.info(f"User said: {message.content}")
        await asyncio.sleep(1)
        await next_bot_line()


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    """
    Configure and run the voice assistant pipeline.

    This chatbot integrates three core AI services:
      - Deepgram for Speech-to-Text (STT)
      - OpenAI for conversational reasoning (LLM)
      - Cartesia for Text-to-Speech (TTS)
    """
    logger.info(f"Starting bot")

    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))

    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        voice_id="71a7ad14-091c-4e8e-a314-022ece01c121",  # British Reading Lady
    )

    llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"))

    # The bot acts as the *customer*
    claim_number = generate_claim_number()
    messages = [
        {
            "role": "system",
            "content": (
                f"You are a customer calling an insurance company. "
                f"Your claim number is {claim_number}. "
                "Remember this exact number and provide it if the agent asks. "
                "You need help with your insurance claim. "
                "You will ask the human about the claim details, such as when it was submitted or its status. "
                "Keep responses brief and natural."
            ),
        },
    ]

    context = LLMContext(messages)
    context_aggregator = LLMContextAggregatorPair(context)
    rtvi = RTVIProcessor(config=RTVIConfig(config=[]))

    pipeline = Pipeline(
        [
            transport.input(),  # Transport user input
            rtvi,               # RTVI processor
            stt,                # Speech-to-text
            transcript.user(),              # Captures user transcripts
            context_aggregator.user(),  # User messages
            llm,                # Language model
            tts,                # Text-to-speech
            transport.output(), # Send audio back
            transcript.assistant(),         # Captures assistant transcripts
            context_aggregator.assistant(),  # Store bot messages
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        observers=[RTVIObserver(rtvi)],
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected")
        start_msg = "Hello! How can I help you today?"
        messages.append({"role": "assistant", "content": start_msg})
        await scripted_conversation(task, messages, context, context_aggregator, claim_number)

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=runner_args.handle_sigint)
    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    """Main bot entry point for the bot starter."""
    transport_params = {
        "webrtc": lambda: TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
            turn_analyzer=LocalSmartTurnAnalyzerV3(),
        ),
    }

    runner_args.transport = "webrtc"
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main
    main()
