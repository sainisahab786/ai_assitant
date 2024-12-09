from fastapi import FastAPI, WebSocket, Request
from ibm_watson import SpeechToTextV1, TextToSpeechV1, AssistantV2
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
import base64
import json

# Watson API Keys and Configurations
STT_API_KEY = 'cGoDyVyzeMA6t9ScjTsqPHyWkE1PrVlA_WU4N-69g7FS'
TTS_API_KEY = 'Jd-deDjHrPDgJj8LcBFXynoU8hBxpQAH_8BcQfb43'
ASSISTANT_API_KEY = '5JsxAzUT0wBFBHx6RiElA1-xls80dLPPGEzhJxD1BJTT'
ASSISTANT_ID = '78935058-e696-43c1-8782-18e7a48f3a6f'

# Watson Service Initializations
stt_authenticator = IAMAuthenticator(STT_API_KEY)
speech_to_text = SpeechToTextV1(authenticator=stt_authenticator)
speech_to_text.set_service_url('https://api.au-syd.speech-to-text.watson.cloud.ibm.com/instances/ec3a80af-af43-4877-bd43-f2eeb0f3ecc5')

tts_authenticator = IAMAuthenticator(TTS_API_KEY)
text_to_speech = TextToSpeechV1(authenticator=tts_authenticator)
text_to_speech.set_service_url('https://api.au-syd.text-to-speech.watson.cloud.ibm.com/instances/efc575b7-f547-4532-ac9b-96a0d5283b77')

assistant_authenticator = IAMAuthenticator(ASSISTANT_API_KEY)
assistant = AssistantV2(version='2024-08-25', authenticator=assistant_authenticator)
assistant.set_service_url('https://api.us-south.assistant.watson.cloud.ibm.com/instances/65f8e216-8bef-4e80-9aa1-0c3909617af0')

# FastAPI App
app = FastAPI()

@app.post("/media-stream")
async def media_stream(request: Request):
    """Handles Twilio Media Stream webhook setup."""
    data = await request.json()
    print(f"Webhook Received: {data}")
    return {"message": "Webhook received successfully."}

@app.websocket("/media-stream/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Handles real-time media streaming from Twilio."""
    await websocket.accept()
    try:
        print("WebSocket connection established.")
        while True:
            # Receive message from Twilio
            message = await websocket.receive_text()
            data = json.loads(message)

            if "media" in data:
                # Decode Base64 audio payload
                audio_chunk = base64.b64decode(data["media"]["payload"])

                # Transcribe audio using Watson Speech-to-Text
                transcription_result = speech_to_text.recognize(
                    audio=audio_chunk,
                    content_type='audio/mulaw;rate=8000'
                ).get_result()

                if transcription_result['results']:
                    transcript = transcription_result['results'][0]['alternatives'][0]['transcript']
                    print(f"Transcribed Text: {transcript}")

                    # Get response from Watson Assistant
                    assistant_response = get_assistant_response(transcript)
                    print(f"Assistant Response: {assistant_response}")

                    # Synthesize Assistant response to speech
                    tts_response = text_to_speech.synthesize(
                        text=assistant_response,
                        voice="en-US_AllisonV3Voice",
                        accept="audio/wav"
                    ).get_result()

                    # Send synthesized audio back to Twilio
                    await websocket.send_text(base64.b64encode(tts_response.content).decode('utf-8'))
                    print("Sent synthesized audio back to Twilio.")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("WebSocket connection closed.")
        await websocket.close()

def get_assistant_response(text):
    """Gets a response from Watson Assistant."""
    try:
        session = assistant.create_session(assistant_id=ASSISTANT_ID).get_result()
        session_id = session['session_id']

        response = assistant.message(
            assistant_id=ASSISTANT_ID,
            session_id=session_id,
            input={'message_type': 'text', 'text': text}
        ).get_result()

        if 'output' in response and 'generic' in response['output']:
            return response['output']['generic'][0]['text']
        else:
            return "I'm sorry, I couldn't understand that."

    except Exception as e:
        print(f"Error in Assistant response: {e}")
        return "An error occurred while processing your request."

