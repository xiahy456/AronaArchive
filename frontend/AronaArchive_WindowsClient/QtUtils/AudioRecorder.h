/*
 * AronaArchive - 自循环 AI
 * Copyright (C) 2026 xia_hy456
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 * SPDX-License-Identifier: GPL-3.0-or-later
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
