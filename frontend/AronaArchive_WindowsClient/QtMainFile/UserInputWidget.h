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
