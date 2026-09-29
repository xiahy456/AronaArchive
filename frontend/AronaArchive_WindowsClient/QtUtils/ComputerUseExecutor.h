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
