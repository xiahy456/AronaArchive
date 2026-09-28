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

#pragma once
#ifndef AUDIORECORDER_H
#define AUDIORECORDER_H

#include "Defines.h"

#include <QObject>
#include <QAudioSource>
#include <QMediaDevices>
#include <QAudioDevice>
#include <QAudioFormat>
#include <QIODevice>
#include <QByteArray>

class AudioRecorder : public QObject
{
    Q_OBJECT

public:
    explicit AudioRecorder(QObject* parent = nullptr);
    ~AudioRecorder();

    bool startRecording();
    void stopRecording();
    bool isRecording() const;
    void setPlaybackGuard(bool enabled);

signals:
    void errorOccurred(const QString& error);
    void pcmFrameReady(const QByteArray& frame);
    void speechDetected();

private:
    class CaptureDevice;

    void onPcmWritten(const QByteArray& data);
    bool looksLikeSpeech(const QByteArray& data, int* durationMs) const;

    QAudioSource* m_audioSource;
    CaptureDevice* m_captureDevice;
    QAudioFormat m_format;
    bool m_isRecording;
    bool m_playbackGuard;
    int m_speechMs;
    bool m_speechLatched;
};

#endif // AUDIORECORDER_H
