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

#include <Defines.h>
#include <GlobalVariables.h>
#include "MainController.h"

#include <QObject>
#include <QHotKey>
#include <QKeySequence>
#include <QApplication>

class ShortCutKey  : public QObject
{
	Q_OBJECT

public:
	ShortCutKey(MainController* mainController);
	~ShortCutKey();

private slots:
	void onSwitchAudioInput();
	void onSwitchMouseTransparent();
	void onShowUserInput();
	void onSwitchImageInput();
	void onCancelComputerUse();

private:
	MainController* m_mainController = nullptr;
	QHotkey* m_switchAudioInput = nullptr;
	QHotkey* m_switchMouseTransparent = nullptr;
	QHotkey* m_showUserInput = nullptr;
	QHotkey* m_switchImageInput = nullptr;
	QHotkey* m_cancelComputerUse = nullptr;
	bool m_switchAudioInputEnabled = false;

};
