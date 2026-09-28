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
#ifndef COMPUTERUSEEXECUTOR_H
#define COMPUTERUSEEXECUTOR_H

#include <QJsonObject>
#include <QList>
#include <QObject>
#include <QPointer>
#include <QRect>
#include <QString>
#include <QTimer>
#include <QWidget>

class QScreen;

class ComputerUseExecutor : public QObject
{
	Q_OBJECT

public:
	explicit ComputerUseExecutor(QObject* parent = nullptr);

	void setExcludeWindows(const QList<QWidget*>& widgets);
	void cancel();
	bool isBusy() const;

public slots:
	void execute(const QJsonObject& action);

signals:
	void observationReady(const QJsonObject& observation);

private:
	void finish(bool ok, const QString& error);
	void captureAndFinish(bool ok, const QString& error);
	void scheduleCapture(int delayMs, bool ok, const QString& error);
	bool performAction(const QJsonObject& action, QString* error);
	bool mapPoint(double x, double y, const QString& coordSpace, int* outX, int* outY, QString* error) const;
	bool sendMouseMove(int x, int y, QString* error);
	bool sendMouseButton(int downFlag, int upFlag, QString* error);
	bool sendMouseDown(int downFlag, QString* error);
	bool sendMouseUp(int upFlag, QString* error);
	bool sendDrag(int startX, int startY, int endX, int endY, int downFlag, int upFlag, QString* error);
	bool sendKeyCombo(const QString& combo, QString* error);
	bool sendUnicodeText(const QString& text, QString* error);
	bool sendScroll(int dy, QString* error);
	bool pointHitsArona() const;
	void releaseButtons();
	void lockScreenForRun(const QString& runId);

	QList<QPointer<QWidget>> m_excludeWindows;
	QTimer* m_delayTimer = nullptr;
	QString m_runId;
	int m_step = 0;
	QString m_lockedRunId;
	QPointer<QScreen> m_lockedScreen;
	QRect m_lockedGeom;
	int m_lastImgW = 0;
	int m_lastImgH = 0;
	bool m_busy = false;
	bool m_cancelled = false;
	bool m_leftDown = false;
	bool m_rightDown = false;
	bool m_middleDown = false;
	bool m_pendingOk = true;
	QString m_pendingError;
};

#endif // COMPUTERUSEEXECUTOR_H
