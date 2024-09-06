import json
import boto3
from pydub import AudioSegment
from io import BytesIO
import io
import requests
from urllib.parse import urlparse
import re

# Specify the path to the ffmpeg binary
AudioSegment.converter = "/opt/bin/ffmpeg"

s3 = boto3.client('s3')

PROJECT_BUCKET = "matesub-video-optimized"
EXPORT_BUCKET = "matedub-api-export-staging"
REGIONS_FILES_BUCKET = "matedub-api-cache-files-staging "


def download_audio(url):
    response = requests.get(url)
    return AudioSegment.from_file(BytesIO(response.content))


def lambda_handler(event, context):
    message_data = json.loads(event)

    project_id = message_data['project_id']
    locale = message_data['locale']
    regions = message_data['regions']
    force_generation = message_data['force_generation']
    no_vocal_key = message_data['no_vocal_key']
    video_key = message_data['video_key']

    file_name = create_audio(regions, project_id, locale, force_generation, no_vocal_key)

    # Step 2: Start the AWS MediaConvert job
    video_input_s3 = f"s3://{PROJECT_BUCKET}/{video_key}"
    audio_input_s3 = f"s3://{EXPORT_BUCKET}/{file_name}"
    output_s3 = f"s3://{EXPORT_BUCKET}/{project_id}/dubbed_{video_key}"

    return {
        'statusCode': 200,
        'body': json.dumps(
            {
                'video_input_s3': video_input_s3,
                'audio_input_s3': audio_input_s3,
                'output_s3': output_s3}
        )
    }


def create_audio(regions: list, project_id, locale, force_generation, no_vocal_key):
    file_name = f"{project_id}/dub_audio_background_{locale}.wav"

    if not force_generation and file_exists(EXPORT_BUCKET, file_name):
        print("API::Libs::AudioExporter::export: File already exists")
        return file_name

    if not are_region_valid(regions):
        print("API::Libs::AudioExporter::export: Invalid regions")
        # todo send error message
        return

    with io.BytesIO() as overlay_buffer:
        s3.download_fileobj(PROJECT_BUCKET, no_vocal_key, overlay_buffer)
        overlay_buffer.seek(0)
        background_audio = AudioSegment.from_file(overlay_buffer)

    audio = concatenate(regions, background_audio)

    with io.BytesIO() as buffer:
        audio.export(buffer, format="wav")
        buffer.seek(0)
        upload_from_buffer(buffer, file_name)

    print("API::Libs::AudioExporter::export: DONE Matedub export")
    return file_name


def concatenate(regions: list, background_audio: AudioSegment):
    print("API::Libs::AudioExporter::concatenate: starting merge_and_mix_segments")
    regions = sorted(regions, key=lambda x: float(x["start"]))
    for region in regions:
        start_time = region["start"] * 1000
        parsed_url = urlparse(region["url"])
        object_key = parsed_url.path.lstrip('/')
        response = s3.get_object(Bucket=REGIONS_FILES_BUCKET, Key=object_key)
        audio_data = response['Body'].read()
        region_audio = AudioSegment.from_file(io.BytesIO(audio_data))
        background_audio = background_audio.overlay(region_audio, position=start_time)
    return background_audio.set_frame_rate(44000)


def normalize_name(name):
    for string in [' ', '.mp4', '.avi', '.mov']:
        name = name.replace(string, '')
    name = re.sub(r'[^a-zA-Z0-9]', '', name)
    return name


def are_region_valid(regions: list):
    for region in regions:
        for key in ["start", "end", "url"]:
            if key not in region:
                message = f"Field {key} not present in segment {region}"
                print(f"API::Libs::AudioExporter::check_if_segments_are_valid_matedub_audio_export: {message}")
                return False
    return True


def file_exists(bucket_name, object_key):
    try:
        s3.head_object(Bucket=bucket_name, Key=object_key)
        return True
    except Exception as e:
        print(f"The file with key '{object_key}' does not exist in bucket '{bucket_name}'.")
        return False


def upload_from_buffer(buffer, s3_key):
    client = boto3.Session().resource('s3')
    client.Bucket(EXPORT_BUCKET).upload_fileobj(
        buffer,
        s3_key,
        Config=boto3.s3.transfer.TransferConfig(use_threads=False),
        ExtraArgs={"ACL": "public-read"}
    )
