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


#include "ShortCutKey.h"

ShortCutKey::ShortCutKey(MainController* mainController)
	: m_mainController(mainController)
{
	// 注册快捷键
	m_switchAudioInput = new QHotkey(QKeySequence(GET_STRING_FROM_JSON(_global_config, "short_cut_key", "switch_audio_input")), true, this);
	m_switchMouseTransparent = new QHotkey(QKeySequence(GET_STRING_FROM_JSON(_global_config, "short_cut_key", "switch_mouse_transparent")), true, this);
	m_showUserInput = new QHotkey(QKeySequence(GET_STRING_FROM_JSON(_global_config, "short_cut_key", "show_user_input")), true, this);
	QString switchImageInputSeq = GET_STRING_FROM_JSON(_global_config, "short_cut_key", "switch_image_input");
	if (switchImageInputSeq.isEmpty()) {
		switchImageInputSeq = QStringLiteral("Ctrl+Alt+X");
	}
	m_switchImageInput = new QHotkey(QKeySequence(switchImageInputSeq), true, this);
	QString cancelComputerUseSeq = GET_STRING_FROM_JSON(_global_config, "short_cut_key", "cancel_computer_use");
	if (cancelComputerUseSeq.isEmpty()) {
		cancelComputerUseSeq = QStringLiteral("Ctrl+Alt+S");
	}
	m_cancelComputerUse = new QHotkey(QKeySequence(cancelComputerUseSeq), true, this);

	// 注册结果日志
	if (m_switchAudioInput->isRegistered()) FINE_DEBUG_OUTPUT("[Short Cut Key]Key 'Switch Audio Input' registered succeed! Registered to: "
		+ GET_STRING_FROM_JSON(_global_config, "short_cut_key", "switch_audio_input"));
	else ERROR_DEBUG_OUTPUT("[Short Cut Key]Key 'Switch Audio Input' registered failed! It might be occupied! Registered to:"
		+ GET_STRING_FROM_JSON(_global_config, "short_cut_key", "switch_audio_input"));
	if (m_switchMouseTransparent->isRegistered()) FINE_DEBUG_OUTPUT("[Short Cut Key]Key 'Switch Mouse Transparent' registered succeed! Registered to: "
		+ GET_STRING_FROM_JSON(_global_config, "short_cut_key", "switch_mouse_transparent"));
	else ERROR_DEBUG_OUTPUT("[Short Cut Key]Key 'Switch Mouse Transparent' registered failed! It might be occupied! Registered to:"
		+ GET_STRING_FROM_JSON(_global_config, "short_cut_key", "switch_mouse_transparent"));
	if (m_showUserInput->isRegistered()) FINE_DEBUG_OUTPUT("[Short Cut Key]Key 'Show User Input' registered succeed! Registered to: "
		+ GET_STRING_FROM_JSON(_global_config, "short_cut_key", "show_user_input"));
	else ERROR_DEBUG_OUTPUT("[Short Cut Key]Key 'Show User Input' registered failed! It might be occupied! Registered to:"
		+ GET_STRING_FROM_JSON(_global_config, "short_cut_key", "show_user_input"));
	if (m_switchImageInput->isRegistered()) FINE_DEBUG_OUTPUT("[Short Cut Key]Key 'Switch Image Input' registered succeed! Registered to: "
		+ switchImageInputSeq);
	else ERROR_DEBUG_OUTPUT("[Short Cut Key]Key 'Switch Image Input' registered failed! It might be occupied! Registered to:"
		+ switchImageInputSeq);
	if (m_cancelComputerUse->isRegistered()) FINE_DEBUG_OUTPUT("[Short Cut Key]Key 'Cancel Computer Use' registered succeed! Registered to: "
		+ cancelComputerUseSeq);
	else ERROR_DEBUG_OUTPUT("[Short Cut Key]Key 'Cancel Computer Use' registered failed! It might be occupied! Registered to:"
		+ cancelComputerUseSeq);

	// 连接信号
	connect(m_switchAudioInput, &QHotkey::activated, this, &ShortCutKey::onSwitchAudioInput);
	connect(m_switchMouseTransparent, &QHotkey::activated, this, &ShortCutKey::onSwitchMouseTransparent);
	connect(m_showUserInput, &QHotkey::activated, this, &ShortCutKey::onShowUserInput);
	connect(m_switchImageInput, &QHotkey::activated, this, &ShortCutKey::onSwitchImageInput);
	connect(m_cancelComputerUse, &QHotkey::activated, this, &ShortCutKey::onCancelComputerUse);

}

ShortCutKey::~ShortCutKey()
{

}

void ShortCutKey::onSwitchAudioInput()
{
	FINE_DEBUG_OUTPUT("[Short Cut Key]Key 'Switch Audio Input' activated!");
	if (m_mainController->isListening()) {
		m_mainController->stopAudioProcessing();
		m_switchAudioInputEnabled = false;
	}
	else {
		m_mainController->startAudioProcessing();
		m_switchAudioInputEnabled = m_mainController->isListening();
	}
}

void ShortCutKey::onSwitchMouseTransparent()
{
	FINE_DEBUG_OUTPUT("[Short Cut Key]Key 'Switch Mouse Transparent' activated!");
	m_mainController->toggleMouseTransparent();
}

void ShortCutKey::onShowUserInput()
{
	FINE_DEBUG_OUTPUT("[Short Cut Key]Key 'Show User Input' activated!");
	m_mainController->showUserInput();
}

void ShortCutKey::onSwitchImageInput()
{
	FINE_DEBUG_OUTPUT("[Short Cut Key]Key 'Switch Image Input' activated!");
	m_mainController->toggleImageInput();
}

void ShortCutKey::onCancelComputerUse()
{
	FINE_DEBUG_OUTPUT("[Short Cut Key]Key 'Cancel Computer Use' activated!");
	m_mainController->cancelComputerUse();
}

