import json
import boto3
from pydub import AudioSegment
from io import BytesIO
import requests

# Specify the path to the ffmpeg binary
AudioSegment.converter = "/opt/bin/ffmpeg"

s3 = boto3.client('s3')


def download_audio(url):
    response = requests.get(url)
    return AudioSegment.from_file(BytesIO(response.content))


def lambda_handler(event, context):
    try:
        # Extract URLs from the event
        audio1_url = event['audio1_url']
        audio2_url = event['audio2_url']

        # Download the audio files
        audio1 = download_audio(audio1_url)
        audio2 = download_audio(audio2_url)

        # Overlay the audio files
        combined = audio1.overlay(audio2)

        # Export the combined audio to a file or a stream (for simplicity here we're exporting to a BytesIO object)
        output = BytesIO()
        combined.export(output, format="mp3")

        # Return success message
        return {
            'statusCode': 200,
            'body': json.dumps('Audio merged')
        }

    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps(f"Error: {str(e)}")
        }
