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

#include <QWidget>
#include <QKeyEvent>
#include <QEvent>
#include <QResizeEvent>
#include <QRect>
#include <QFont>
#include <QString>
#include <QVector>
#include <QSequentialAnimationGroup>
#include <QPropertyAnimation>
#include <QEasingCurve>
#include "ui_UserInputWidget.h"

#include "GlobalInclude.h"
#include "BlueakaFontLoader.h"

class QLineEdit;
class ParallelogramWidget;

class UserInputWidget : public QWidget
{
	Q_OBJECT

public:
	UserInputWidget(QWidget *parent = nullptr);
	~UserInputWidget();

	void showForInput();

signals:
	void textSubmitted(const QString& text);

protected:
	void keyPressEvent(QKeyEvent* event) override;
	void changeEvent(QEvent* event) override;
	bool eventFilter(QObject* watched, QEvent* event) override;
	void resizeEvent(QResizeEvent* event) override;

private:
	struct InputRow {
		ParallelogramWidget* bg = nullptr;
		QLineEdit* edit = nullptr;
	};

	static constexpr int kCharsPerRow = 50;

	Ui::UserInputWidgetClass ui;

	QVector<InputRow> m_rows;
	QRect m_baseGeometry;
	QRect m_normalGeometry;
	QFont m_inputFont;
	QString m_backgroundImagePath;
	QString m_placeholderText;
	int m_rowWidth = 0;
	int m_rowHeight = 0;
	int m_rowGap = 0;
	bool m_isSubmitting = false;
	bool m_redistributing = false;
	bool m_imeComposing = false;
	QSequentialAnimationGroup* m_bounceAnimation = nullptr;

	void onReturnPressed();
	void onRowTextChanged();
	void playSubmitBounceAnimation();
	void syncChildrenGeometry();
	void stopBounceAndHide();

	InputRow createRow();
	void connectRow(const InputRow& row);
	void setRowCount(int count);
	void updatePlaceholder();
	void updateWindowGeometryForRows();
	QString joinedText() const;
	int neededRowCount(int textLength) const;
	int rowIndexOfEdit(const QObject* watched) const;
	int logicalCursorFrom(QLineEdit* source) const;
	void applyJoinedText(const QString& text, int logicalCursor);
	void applyCursor(int logicalCursor, int textLength);
	bool handleRowKeyPress(QLineEdit* edit, QKeyEvent* keyEvent);
};
