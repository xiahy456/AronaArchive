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

#include "UserInputWidget.h"

#include <QApplication>
#include <QInputMethodEvent>
#include <QLineEdit>
#include <QScreen>

#include "ParallelogramWidget.h"

UserInputWidget::UserInputWidget(QWidget *parent)
	: QWidget(parent)
{
	ui.setupUi(this);

    // 窗口设置
    this->setAttribute(Qt::WA_TranslucentBackground);	// 设置窗口背景透明
    this->setWindowFlag(Qt::FramelessWindowHint);	// 设置无边框窗口
    this->setWindowFlag(Qt::WindowStaysOnTopHint);	// 设置窗口始终在顶部
    this->setWindowFlag(Qt::Tool);	// 隐藏应用程序图标
    this->setAutoFillBackground(false);   // 禁用自动填充背景
    this->setWindowTitle(GET_STRING_FROM_JSON(_global_dict, "application_data", "user_input_widget_name"));  // 设置窗口名称

    m_rowWidth = 940 * WIDGET_ZOOM;
    m_rowHeight = 25 * WIDGET_ZOOM;
    m_rowGap = 16 * WIDGET_ZOOM;
    m_backgroundImagePath = GET_STRING_FROM_JSON(_global_config, "settings", "top_information_path");
    m_placeholderText = GET_STRING_FROM_JSON(_global_dict, "application_data", "user_input_widget_placeholder");
    m_inputFont = BlueakaFontLoader::instance()->createFont(11 * WIDGET_ZOOM);

    // 设置窗口大小并居中靠下放置
    this->resize(m_rowWidth, m_rowHeight);
    QScreen* screen = QApplication::primaryScreen();
    QRect screenRect = screen->availableGeometry();
    this->move(screenRect.left() + (screenRect.width() - this->width()) / 2,
        screenRect.bottom() - this->height() - 180 * WIDGET_ZOOM);
    m_baseGeometry = this->geometry();
    m_normalGeometry = m_baseGeometry;

	// 输入背景
    ui.inputBGWidget->move(0 * WIDGET_ZOOM, 0 * WIDGET_ZOOM);
    ui.inputBGWidget->setFixedSize(m_rowWidth, m_rowHeight);
    ui.inputBGWidget->setFillBackground(true);
    ui.inputBGWidget->setBackgroundImage(m_backgroundImagePath);
    ui.inputBGWidget->show();

    // 输入框
    ui.inputLineEdit->move(0 * WIDGET_ZOOM, 0 * WIDGET_ZOOM);
    ui.inputLineEdit->resize(m_rowWidth, m_rowHeight);
    ui.inputLineEdit->setFont(m_inputFont);
    ui.inputLineEdit->setAlignment(Qt::AlignCenter);
    ui.inputLineEdit->setStyleSheet(
        "color: rgb(44, 69, 99);"
        "background: transparent;"
        "border: none;"
    );
    ui.inputLineEdit->clear();
    ui.inputLineEdit->setPlaceholderText(m_placeholderText);
    ui.inputLineEdit->show();
    ui.inputLineEdit->raise();

    InputRow first;
    first.bg = ui.inputBGWidget;
    first.edit = ui.inputLineEdit;
    m_rows.append(first);
    connectRow(first);
}

UserInputWidget::~UserInputWidget()
{}

void UserInputWidget::showForInput()
{
    if (m_bounceAnimation) {
        QSequentialAnimationGroup* anim = m_bounceAnimation;
        m_bounceAnimation = nullptr;
        anim->disconnect(this);
        anim->stop(); // DeleteWhenStopped
    }
    m_isSubmitting = false;
    m_imeComposing = false;

    m_redistributing = true;
    setRowCount(1);
    m_rows.first().edit->clear();
    m_redistributing = false;
    updatePlaceholder();

    m_normalGeometry = m_baseGeometry;
    this->setGeometry(m_baseGeometry);
    syncChildrenGeometry();
    this->show();
    this->raise();
    this->activateWindow();
    m_rows.first().edit->setFocus(Qt::OtherFocusReason);
}

void UserInputWidget::onReturnPressed()
{
    if (m_isSubmitting) {
        return;
    }

    const QString text = joinedText().trimmed();
    if (text.isEmpty()) {
        this->hide();
        return;
    }

    // 发送信号必须早于或等于弹跳动画开始
    emit textSubmitted(text);
    playSubmitBounceAnimation();
}

void UserInputWidget::onRowTextChanged()
{
    if (m_redistributing || m_imeComposing || m_isSubmitting) {
        return;
    }

    QLineEdit* edit = qobject_cast<QLineEdit*>(sender());
    const QString text = joinedText();
    const int cursor = edit ? logicalCursorFrom(edit) : text.size();
    applyJoinedText(text, cursor);
}

void UserInputWidget::playSubmitBounceAnimation()
{
    m_isSubmitting = true;
    m_normalGeometry = this->geometry();

    const QRect normal = m_normalGeometry;
    const int shrinkW = qMax(1, qRound(normal.width() * 0.92));
    const int shrinkH = qMax(1, qRound(normal.height() * 0.70));
    const QRect shrunk(
        normal.center().x() - shrinkW / 2,
        normal.center().y() - shrinkH / 2,
        shrinkW,
        shrinkH
    );

    if (m_bounceAnimation) {
        QSequentialAnimationGroup* anim = m_bounceAnimation;
        m_bounceAnimation = nullptr;
        anim->stop(); // DeleteWhenStopped
    }

    auto* shrinkAnim = new QPropertyAnimation(this, "geometry");
    shrinkAnim->setDuration(150);
    shrinkAnim->setStartValue(normal);
    shrinkAnim->setEndValue(shrunk);
    shrinkAnim->setEasingCurve(QEasingCurve::InQuad);

    auto* restoreAnim = new QPropertyAnimation(this, "geometry");
    restoreAnim->setDuration(350);
    restoreAnim->setStartValue(shrunk);
    restoreAnim->setEndValue(normal);
    restoreAnim->setEasingCurve(QEasingCurve::OutBounce);

    m_bounceAnimation = new QSequentialAnimationGroup(this);
    m_bounceAnimation->addAnimation(shrinkAnim);
    m_bounceAnimation->addAnimation(restoreAnim);

    connect(m_bounceAnimation, &QSequentialAnimationGroup::finished, this, [this]() {
        m_bounceAnimation = nullptr;
        m_isSubmitting = false;
        this->setGeometry(m_normalGeometry);
        syncChildrenGeometry();
        this->hide();
    });

    m_bounceAnimation->start(QAbstractAnimation::DeleteWhenStopped);
}

void UserInputWidget::syncChildrenGeometry()
{
    const int n = m_rows.size();
    if (n <= 0) {
        return;
    }

    const int w = this->width();
    const int h = this->height();
    const int expectedH = m_rowHeight * n + m_rowGap * (n - 1);
    const double scale = expectedH > 0 ? static_cast<double>(h) / expectedH : 1.0;
    const int gap = qMax(0, qRound(m_rowGap * scale));
    const int rowH = qMax(1, (h - gap * (n - 1)) / n);

    int y = 0;
    for (int i = 0; i < n; ++i) {
        m_rows[i].bg->move(0, y);
        m_rows[i].bg->setFixedSize(w, rowH);
        m_rows[i].bg->show();
        m_rows[i].edit->move(0, y);
        m_rows[i].edit->resize(w, rowH);
        m_rows[i].edit->show();
        m_rows[i].edit->raise();
        y += rowH + gap;
    }
}

void UserInputWidget::stopBounceAndHide()
{
    if (m_bounceAnimation) {
        QSequentialAnimationGroup* anim = m_bounceAnimation;
        m_bounceAnimation = nullptr;
        anim->disconnect(this);
        anim->stop(); // DeleteWhenStopped
    }
    m_isSubmitting = false;
    this->setGeometry(m_normalGeometry);
    syncChildrenGeometry();
    this->hide();
}

void UserInputWidget::keyPressEvent(QKeyEvent* event)
{
    if (event->key() == Qt::Key_Escape) {
        stopBounceAndHide();
        event->accept();
        return;
    }
    QWidget::keyPressEvent(event);
}

bool UserInputWidget::eventFilter(QObject* watched, QEvent* event)
{
    const int rowIndex = rowIndexOfEdit(watched);
    if (rowIndex < 0) {
        return QWidget::eventFilter(watched, event);
    }

    QLineEdit* edit = m_rows[rowIndex].edit;

    if (event->type() == QEvent::InputMethod) {
        QInputMethodEvent* imeEvent = static_cast<QInputMethodEvent*>(event);
        m_imeComposing = !imeEvent->preeditString().isEmpty();
        return QWidget::eventFilter(watched, event);
    }

    if (event->type() == QEvent::KeyPress) {
        QKeyEvent* keyEvent = static_cast<QKeyEvent*>(event);
        if (keyEvent->key() == Qt::Key_Escape) {
            stopBounceAndHide();
            return true;
        }
        if (!m_imeComposing && handleRowKeyPress(edit, keyEvent)) {
            return true;
        }
    }

    return QWidget::eventFilter(watched, event);
}

void UserInputWidget::changeEvent(QEvent* event)
{
    // 提交动画、重排加行期间忽略失焦关闭，避免第二条出现时把浮层关掉
    if (event->type() == QEvent::WindowDeactivate && this->isVisible()
        && !m_isSubmitting && !m_redistributing) {
        this->hide();
    }
    QWidget::changeEvent(event);
}

void UserInputWidget::resizeEvent(QResizeEvent* event)
{
    QWidget::resizeEvent(event);
    syncChildrenGeometry();
}

UserInputWidget::InputRow UserInputWidget::createRow()
{
    const int index = m_rows.size();
    const int y = index * (m_rowHeight + m_rowGap);

    InputRow row;
    row.bg = new ParallelogramWidget(this);
    row.bg->setParent(this);
    row.bg->move(0, y);
    row.bg->setFixedSize(m_rowWidth, m_rowHeight);
    row.bg->setFillBackground(true);
    row.bg->setBackgroundImage(m_backgroundImagePath);
    row.bg->show();

    row.edit = new QLineEdit(this);
    row.edit->setParent(this);
    row.edit->move(0, y);
    row.edit->resize(m_rowWidth, m_rowHeight);
    row.edit->setFont(m_inputFont);
    row.edit->setAlignment(Qt::AlignCenter);
    row.edit->setStyleSheet(
        "color: rgb(44, 69, 99);"
        "background: transparent;"
        "border: none;"
    );
    row.edit->setPlaceholderText(QString());
    row.edit->show();
    row.edit->raise();

    connectRow(row);
    return row;
}

void UserInputWidget::connectRow(const InputRow& row)
{
    row.edit->installEventFilter(this);
    connect(row.edit, &QLineEdit::returnPressed, this, &UserInputWidget::onReturnPressed);
    connect(row.edit, &QLineEdit::textChanged, this, &UserInputWidget::onRowTextChanged);
}

void UserInputWidget::setRowCount(int count)
{
    count = qMax(1, count);

    QWidget* focusWidget = QApplication::focusWidget();
    while (m_rows.size() > count) {
        InputRow row = m_rows.takeLast();
        if (focusWidget == row.edit && !m_rows.isEmpty()) {
            m_rows.last().edit->setFocus(Qt::OtherFocusReason);
        }
        row.edit->hide();
        row.bg->hide();
        row.edit->deleteLater();
        row.bg->deleteLater();
    }

    while (m_rows.size() < count) {
        m_rows.append(createRow());
    }
}

void UserInputWidget::updatePlaceholder()
{
    if (m_rows.isEmpty()) {
        return;
    }

    const bool showPlaceholder = (m_rows.size() == 1 && m_rows.first().edit->text().isEmpty());
    m_rows.first().edit->setPlaceholderText(showPlaceholder ? m_placeholderText : QString());
    for (int i = 1; i < m_rows.size(); ++i) {
        m_rows[i].edit->setPlaceholderText(QString());
    }
}

void UserInputWidget::updateWindowGeometryForRows()
{
    if (m_isSubmitting) {
        return;
    }

    const int n = qMax(1, m_rows.size());
    const int newH = m_rowHeight * n + m_rowGap * (n - 1);
    QScreen* screen = QApplication::primaryScreen();
    const QRect screenRect = screen->availableGeometry();

    int x = m_baseGeometry.x();
    int y = m_baseGeometry.y();
    const int screenBottom = screenRect.y() + screenRect.height();
    if (y + newH > screenBottom) {
        y = screenBottom - newH;
    }
    if (y < screenRect.y()) {
        y = screenRect.y();
    }

    m_normalGeometry = QRect(x, y, m_rowWidth, newH);
    this->setGeometry(m_normalGeometry);
    syncChildrenGeometry();
}

QString UserInputWidget::joinedText() const
{
    QString text;
    for (const InputRow& row : m_rows) {
        text += row.edit->text();
    }
    return text;
}

int UserInputWidget::neededRowCount(int textLength) const
{
    if (textLength <= 0) {
        return 1;
    }
    return (textLength + kCharsPerRow - 1) / kCharsPerRow;
}

int UserInputWidget::rowIndexOfEdit(const QObject* watched) const
{
    for (int i = 0; i < m_rows.size(); ++i) {
        if (m_rows[i].edit == watched) {
            return i;
        }
    }
    return -1;
}

int UserInputWidget::logicalCursorFrom(QLineEdit* source) const
{
    int pos = 0;
    for (const InputRow& row : m_rows) {
        if (row.edit == source) {
            return pos + source->cursorPosition();
        }
        pos += row.edit->text().size();
    }
    return pos;
}

void UserInputWidget::applyJoinedText(const QString& text, int logicalCursor)
{
    if (m_redistributing) {
        return;
    }

    m_redistributing = true;
    setRowCount(neededRowCount(text.size()));
    updateWindowGeometryForRows();

    for (int i = 0; i < m_rows.size(); ++i) {
        const QString slice = text.mid(i * kCharsPerRow, kCharsPerRow);
        if (m_rows[i].edit->text() != slice) {
            m_rows[i].edit->setText(slice);
        }
        m_rows[i].bg->show();
        m_rows[i].edit->show();
        m_rows[i].edit->raise();
    }

    updatePlaceholder();
    applyCursor(logicalCursor, text.size());
    m_redistributing = false;
}

void UserInputWidget::applyCursor(int logicalCursor, int textLength)
{
    if (m_rows.isEmpty()) {
        return;
    }

    logicalCursor = qBound(0, logicalCursor, textLength);
    int rowIdx = 0;
    int col = 0;
    if (textLength > 0) {
        rowIdx = logicalCursor / kCharsPerRow;
        col = logicalCursor % kCharsPerRow;
        if (rowIdx >= m_rows.size()) {
            rowIdx = m_rows.size() - 1;
            col = m_rows[rowIdx].edit->text().size();
        }
    }

    QLineEdit* edit = m_rows[rowIdx].edit;
    edit->show();
    edit->raise();
    edit->setFocus(Qt::OtherFocusReason);
    edit->setCursorPosition(col);
}

bool UserInputWidget::handleRowKeyPress(QLineEdit* edit, QKeyEvent* keyEvent)
{
    const int rowIndex = rowIndexOfEdit(edit);
    if (rowIndex < 0) {
        return false;
    }

    const int key = keyEvent->key();
    const Qt::KeyboardModifiers mods = keyEvent->modifiers() & ~Qt::KeypadModifier;
    const bool noModifiers = (mods == Qt::NoModifier);
    const bool shiftOnly = (mods == Qt::ShiftModifier);
    const int cursor = edit->cursorPosition();
    const int editLen = edit->text().size();
    const bool hasSelection = edit->hasSelectedText();

    if (key == Qt::Key_Tab && (noModifiers || shiftOnly)) {
        if (shiftOnly) {
            if (rowIndex > 0) {
                QLineEdit* prev = m_rows[rowIndex - 1].edit;
                prev->setFocus(Qt::TabFocusReason);
                prev->setCursorPosition(prev->text().size());
            }
        } else if (rowIndex + 1 < m_rows.size()) {
            QLineEdit* next = m_rows[rowIndex + 1].edit;
            next->setFocus(Qt::TabFocusReason);
            next->setCursorPosition(0);
        }
        return true;
    }

    if (key == Qt::Key_Backtab) {
        if (rowIndex > 0) {
            QLineEdit* prev = m_rows[rowIndex - 1].edit;
            prev->setFocus(Qt::BacktabFocusReason);
            prev->setCursorPosition(prev->text().size());
        }
        return true;
    }

    if (key == Qt::Key_Left && noModifiers && !hasSelection && cursor == 0 && rowIndex > 0) {
        QLineEdit* prev = m_rows[rowIndex - 1].edit;
        prev->setFocus(Qt::OtherFocusReason);
        prev->setCursorPosition(prev->text().size());
        return true;
    }

    if (key == Qt::Key_Right && noModifiers && !hasSelection && cursor == editLen && rowIndex + 1 < m_rows.size()) {
        QLineEdit* next = m_rows[rowIndex + 1].edit;
        next->setFocus(Qt::OtherFocusReason);
        next->setCursorPosition(0);
        return true;
    }

    if (key == Qt::Key_Backspace && noModifiers && !hasSelection && cursor == 0) {
        const int logical = logicalCursorFrom(edit);
        if (logical > 0) {
            QString text = joinedText();
            text.remove(logical - 1, 1);
            applyJoinedText(text, logical - 1);
            return true;
        }
    }

    if (key == Qt::Key_Delete && noModifiers && !hasSelection && cursor == editLen) {
        const int logical = logicalCursorFrom(edit);
        QString text = joinedText();
        if (logical < text.size()) {
            text.remove(logical, 1);
            applyJoinedText(text, logical);
            return true;
        }
    }

    return false;
}
