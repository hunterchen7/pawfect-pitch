import whisper
import os
import json
from scipy.io import wavfile
from datetime import datetime
from speechbrain.pretrained import EncoderClassifier
import librosa
import torch
from transformers import Wav2Vec2ForSequenceClassification, Wav2Vec2FeatureExtractor

# Audio Processing Functions
def load_audio(file_path):
    """Load the WAV file."""
    rate, data = wavfile.read(file_path)
    print(f"Audio loaded: {file_path} | Sample Rate: {rate} | Duration: {len(data)/rate:.2f} sec")
    return rate, data

def transcribe_audio(file_path, model_name="base", prompt=None):
    """Transcribe audio using Whisper with optional custom prompts."""
    model = whisper.load_model(model_name)
    print(f"Transcribing audio using Whisper ({model_name} model)...")
    result = model.transcribe(file_path, initial_prompt=prompt)
    print("Transcription completed.")
    return result

def segment_audio_by_timestamps(data, rate, segments, output_dir):
    """Segment audio using transcription timestamps."""
    os.makedirs(output_dir, exist_ok=True)
    segment_files = []
    for segment in segments:
        segment_id = segment["id"]
        start_sample = int(segment["start"] * rate)
        end_sample = int(segment["end"] * rate)
        segment_data = data[start_sample:end_sample]
        output_path = os.path.join(output_dir, f"segment_{segment_id}.wav")
        wavfile.write(output_path, rate, segment_data.astype(data.dtype))
        segment_files.append(output_path)
        print(f"Saved: {output_path}")
    return segment_files

def save_transcription_to_json(transcription, output_file):
    """Save transcription result to a JSON file."""
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(transcription, f, ensure_ascii=False, indent=4)
    print(f"Transcription saved to {output_file}")

def generate_unique_output_dir(base_dir, input_file):
    """Generate a unique output directory name."""
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_dir = os.path.join(base_dir, f"{base_name}_{timestamp}")
    os.makedirs(unique_dir, exist_ok=True)
    return unique_dir

def preprocess_audio(file_path, target_sr=16000):
    """Load audio, convert to mono, and resample to 16 kHz."""
    y, sr = librosa.load(file_path, sr=target_sr, mono=True)
    return torch.tensor(y).unsqueeze(0)  # Add batch dimension

# Load the model and processor
def load_emotion_model():
    """Load the Hugging Face Wav2Vec2 model for emotion recognition."""
    model_name = "ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition"
    model = Wav2Vec2ForSequenceClassification.from_pretrained(model_name)
    feature_extractor = Wav2Vec2FeatureExtractor.from_pretrained(model_name)
    return model, feature_extractor

def analyze_emotion_with_huggingface(file_path, model, feature_extractor):
    """Analyze emotions using Hugging Face Wav2Vec2 model."""
    # Load and preprocess audio
    y, sr = librosa.load(file_path, sr=16000, mono=True)  # Resample to 16 kHz
    inputs = feature_extractor(y, sampling_rate=16000, return_tensors="pt", padding=True)

    # Perform inference
    with torch.no_grad():
        logits = model(**inputs).logits

    # Get probabilities and predicted emotion
    probabilities = torch.nn.functional.softmax(logits, dim=-1)[0]
    
    # adjust probabilities to our liking
    probabilities[0] *= 0.99
    probabilities[1] *= 1.03
    probabilities[2] *= 1
    probabilities[3] *= 1
    probabilities[4] *= 1.016
    probabilities[5] *= 1.03
    probabilities[6] *= 1
    probabilities[7] *= 1
    
    predicted_label = torch.argmax(probabilities).item()

    # Emotion labels (specific to this model)
    emotions = ['angry', 'calm', 'disgust', 'fearful', 'happy', 'neutral', 'sad', 'surprised']
    # Convert probabilities to a list
    confidence_scores = probabilities.tolist()    
    
    predicted_emotion = emotions[predicted_label]


    print(f"Predicted Emotion: {predicted_emotion}")
    print(f"Confidence Scores: {confidence_scores}")

    return {
        "predicted_emotion": predicted_emotion,
        "confidence_scores": confidence_scores
    }


def analyze_emotion_with_speechbrain(file_path, model):
    """Analyze emotion using SpeechBrain with raw waveform input."""
    # Preprocess the audio file
    waveform = preprocess_audio(file_path)

    # Pass waveform through the model
    embeddings = model.mods.wav2vec2(waveform)  # Extract features with wav2vec2
    pooled_embeddings = model.mods.avg_pool(embeddings)  # Pool features
    logits = model.mods.output_mlp(pooled_embeddings)  # Map to emotion logits
    probabilities = torch.nn.functional.softmax(logits, dim=-1)  # Convert to probabilities

    # Get the predicted emotion
    predicted_label = torch.argmax(probabilities, dim=-1).item()
    confidence_scores = probabilities.squeeze().tolist()

    # Map predicted label to emotion
    emotions = ["neutral", "happy", "angry", "sad"]  # Adjust based on your model's output order
    predicted_emotion = emotions[predicted_label]

    print(f"Predicted Emotion: {predicted_emotion}")
    print(f"Confidence Scores: {confidence_scores}")

    return {
        "predicted_emotion": predicted_emotion,
        "confidence_scores": confidence_scores
    }


# Main Processing Pipeline
def preprocess_audio_pipeline(input_file, base_output_dir, model_name="base", prompt=None):
    """Complete transcription and emotion analysis pipeline."""
    output_dir = generate_unique_output_dir(base_output_dir, input_file)
    rate, data = load_audio(input_file)

    # Transcribe the audio
    transcription = transcribe_audio(input_file, model_name=model_name, prompt=prompt)

    # Segment audio
    segment_files = segment_audio_by_timestamps(data, rate, transcription["segments"], output_dir)

    # Load Hugging Face emotion model
    print("\nLoading Hugging Face Emotion Recognition model...")
    emotion_model, feature_extractor = load_emotion_model()

    # Analyze emotions for each segment and update transcription segments
    print("\nAnalyzing emotions for each segment...")
    for segment_file, segment in zip(segment_files, transcription["segments"]):
        print(f"Analyzing Segment {segment['id']}...")
        emotion_features = analyze_emotion_with_huggingface(segment_file, emotion_model, feature_extractor)
        # Add emotion analysis directly into the transcription segments
        segment["emotion_analysis"] = emotion_features

    # Save transcription with embedded emotion analysis
    merged_results_file = os.path.join(output_dir, "analysis_results.json")
    with open(merged_results_file, "w", encoding="utf-8") as f:
        json.dump(transcription, f, ensure_ascii=False, indent=4)
    print(f"Analysis results saved to {merged_results_file}")

    return output_dir, segment_files


# Run the pipeline
if __name__ == "__main__":
    base_output_directory = "transcriptions"
    os.makedirs(base_output_directory, exist_ok=True)

    # Example: Process a new file
    input_audio = "sample_good.wav"
    # Custom prompts to filter influencies back in
    custom_prompt = "uh, um, ah, like, you know, well, hmm, uh-huh, okay..."
    output_dir, segments = preprocess_audio_pipeline(
        input_file=input_audio,
        base_output_dir=base_output_directory,
        model_name="base",
        prompt=custom_prompt
    )
    print(f"Audio segments saved in: {output_dir}")
