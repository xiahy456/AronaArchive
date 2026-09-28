/*
 Copyright 2026 xia_hy456. All rights reserved.

 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at

      https://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
*/

#include "AudioRecorder.h"
#include <cmath>

class AudioRecorder::CaptureDevice : public QIODevice
{
public:
    explicit CaptureDevice(AudioRecorder* owner)
        : QIODevice(owner)
        , m_owner(owner)
    {
    }

protected:
    qint64 readData(char* data, qint64 maxlen) override
    {
        Q_UNUSED(data);
        Q_UNUSED(maxlen);
        return -1;
    }

    qint64 writeData(const char* data, qint64 len) override
    {
        if (!m_owner || len <= 0) {
            return len;
        }
        m_owner->onPcmWritten(QByteArray(data, static_cast<int>(len)));
        return len;
    }

private:
    AudioRecorder* m_owner;
};

AudioRecorder::AudioRecorder(QObject* parent)
    : QObject(parent)
    , m_audioSource(nullptr)
    , m_captureDevice(nullptr)
    , m_isRecording(false)
    , m_playbackGuard(false)
    , m_speechMs(0)
    , m_speechLatched(false)
{
    m_format.setSampleRate(16000);
    m_format.setChannelCount(1);
    m_format.setSampleFormat(QAudioFormat::Int16);

    QAudioDevice inputDevice = QMediaDevices::defaultAudioInput();
    if (!inputDevice.isFormatSupported(m_format)) {
        ERROR_DEBUG_OUTPUT("[Audio Recorder]Default format not supported, trying to use nearest...");
        m_format = inputDevice.preferredFormat();
        m_format.setChannelCount(1);
        m_format.setSampleFormat(QAudioFormat::Int16);
    }
}

AudioRecorder::~AudioRecorder()
{
    stopRecording();
}

bool AudioRecorder::startRecording()
{
    if (m_isRecording) {
        return false;
    }

    QAudioDevice inputDevice = QMediaDevices::defaultAudioInput();
    if (inputDevice.isNull()) {
        emit errorOccurred("[Audio Recorder]Failed to find audio input device!");
        return false;
    }

    if (m_audioSource) {
        delete m_audioSource;
        m_audioSource = nullptr;
    }
    if (m_captureDevice) {
        delete m_captureDevice;
        m_captureDevice = nullptr;
    }

    m_speechMs = 0;
    m_speechLatched = false;
    m_captureDevice = new CaptureDevice(this);
    if (!m_captureDevice->open(QIODevice::WriteOnly)) {
        emit errorOccurred("[Audio Recorder]Failed to open capture device!");
        return false;
    }

    m_audioSource = new QAudioSource(inputDevice, m_format, this);
    m_audioSource->start(m_captureDevice);
    m_isRecording = true;
    FINE_DEBUG_OUTPUT("[Audio Recorder]Streaming capture started");
    return true;
}

void AudioRecorder::stopRecording()
{
    if (!m_isRecording) {
        return;
    }
    if (m_audioSource) {
        m_audioSource->stop();
        delete m_audioSource;
        m_audioSource = nullptr;
    }
    if (m_captureDevice) {
        m_captureDevice->close();
        delete m_captureDevice;
        m_captureDevice = nullptr;
    }
    m_isRecording = false;
    m_speechMs = 0;
    m_speechLatched = false;
    FINE_DEBUG_OUTPUT("[Audio Recorder]Streaming capture stopped");
}

bool AudioRecorder::isRecording() const
{
    return m_isRecording;
}

void AudioRecorder::setPlaybackGuard(bool enabled)
{
    m_playbackGuard = enabled;
}

void AudioRecorder::onPcmWritten(const QByteArray& data)
{
    emit pcmFrameReady(data);

    int durationMs = 0;
    const bool speech = looksLikeSpeech(data, &durationMs);
    if (speech) {
        m_speechMs += durationMs;
        const int needMs = m_playbackGuard ? 360 : 240;
        if (!m_speechLatched && m_speechMs >= needMs) {
            m_speechLatched = true;
            emit speechDetected();
        }
    }
    else {
        m_speechMs = 0;
        m_speechLatched = false;
    }
}

bool AudioRecorder::looksLikeSpeech(const QByteArray& data, int* durationMs) const
{
    const int bytesPerSample = 2 * qMax(1, m_format.channelCount());
    const int sampleCount = data.size() / bytesPerSample;
    if (sampleCount <= 0) {
        if (durationMs) {
            *durationMs = 0;
        }
        return false;
    }

    const int rate = qMax(8000, m_format.sampleRate());
    if (durationMs) {
        *durationMs = static_cast<int>(1000.0 * sampleCount / rate);
    }

    const auto* samples = reinterpret_cast<const qint16*>(data.constData());
    double sumSq = 0.0;
    for (int i = 0; i < sampleCount; ++i) {
        const double s = samples[i];
        sumSq += s * s;
    }
    const double rms = std::sqrt(sumSq / sampleCount);
    const double threshold = m_playbackGuard ? 1400.0 : 650.0;
    return rms >= threshold;
}
