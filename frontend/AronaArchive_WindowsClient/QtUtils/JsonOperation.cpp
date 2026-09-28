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

#include <JsonOperation.h>

JsonOperation::JsonOperation()
{
    m_jsonObj = QJsonObject();
}

JsonOperation::JsonOperation(QString file_path)
	: m_filePath(file_path)
{
	// 打开文件
	QFile file(file_path);
	if (!file.open(QIODevice::ReadOnly | QIODevice::Text)) {
		ERROR_DEBUG_OUTPUT("[Json Operation]Failed to open file: " + file_path);
		return;
	}
    FINE_DEBUG_OUTPUT("[Json Operation]Open file succeed! Path: " + file_path);

	// 读取文件内容，解析为QByteArray对象
	QByteArray jsonData = file.readAll();

    // 关闭文件
    file.close();

    // 解析JSON数据
    QJsonParseError parseError;
    QJsonDocument jsonDoc = QJsonDocument::fromJson(jsonData, &parseError);

    // 检查解析是否成功
    if (parseError.error != QJsonParseError::NoError) {
        ERROR_DEBUG_OUTPUT("[Json Operation]Failed to analsis file:" + parseError.errorString());
        ERROR_DEBUG_OUTPUT("[Json Operation]Error at:" + QString::number(parseError.offset));
        return;
    }
    if (jsonDoc.isNull() || !jsonDoc.isObject()) {
        ERROR_DEBUG_OUTPUT("[Json Operation]Invailed json file!");
        return;
    }

    // 获取JSON对象并读取数据
    m_jsonObj = jsonDoc.object();

	// 输出调试信息
	FINE_DEBUG_OUTPUT("[Json Operation]Successfully opened json file: " + file_path);
}

JsonOperation::JsonOperation(const QJsonObject& jsonObj)
    : m_jsonObj(jsonObj)
{

}

JsonOperation::~JsonOperation()
{
}

QVariant JsonOperation::getValue(QString key)
{
	// 定义万能类QVariant对象value，接收JSON对象中对应key的value
    QVariant value;
	value = m_jsonObj[key].toVariant();
    if (!value.isValid()) {
        ERROR_DEBUG_OUTPUT("[Qt Operation]Failed getting value! Target key: " + key);
	}
	// 返回value对象
    return value;
}

QString JsonOperation::getString(QString key)
{
    QJsonValue target_pair = m_jsonObj[key];
    // 判断是不是字符串并返回
    if (target_pair.isString()) return target_pair.toString();
    else {
        ERROR_DEBUG_OUTPUT("[Qt Operation]Failed getting string! Target key: " + key);
        return "";
    }
}

int JsonOperation::getInt(QString key)
{
    int value = (0xffff-5);
    value = m_jsonObj[key].toInt();
    if (value == 0xffff - 5) qWarning().noquote() << ERROR_PR << "[Qt Operation]Failed getting int! Target key: " << key;
    return value;
}

double JsonOperation::getDouble(QString key)
{
    double value = 0.0;
    value = m_jsonObj[key].toDouble();
	return value;
}

bool JsonOperation::getBool(QString key)
{
	bool value = false;
	value = m_jsonObj[key].toBool();
	return value;
}


JsonOperation JsonOperation::getJson(QString key)
{
    QJsonValue target_pair = m_jsonObj[key];
    // 判断是不是Json并返回
    if (target_pair.isObject()) return target_pair.toObject();
    else {
        ERROR_DEBUG_OUTPUT("[Qt Operation]Failed getting json object! Target key: " + key);
        return JsonOperation();
    }
}

QVariant JsonOperation::analysisJson(QString json, QString key)
{
    QJsonDocument jsonDoc = QJsonDocument::fromJson(json.toUtf8());

    if (jsonDoc.isObject()) {
        return jsonDoc.object().value(key).toVariant();
    }

    return QVariant();
}

void JsonOperation::setValue(QString key, const QVariant& value)
{
    m_jsonObj.insert(key, QJsonValue::fromVariant(value));
    FINE_DEBUG_OUTPUT("[Json Operation]Set value for key: " + key);
}

void JsonOperation::setString(QString key, const QString& value)
{
    m_jsonObj.insert(key, QJsonValue(value));
    FINE_DEBUG_OUTPUT("[Json Operation]Set string for key: " + key);
}

void JsonOperation::setInt(QString key, int value)
{
    m_jsonObj.insert(key, QJsonValue(value));
    FINE_DEBUG_OUTPUT("[Json Operation]Set int for key: " + key);
}

void JsonOperation::setDouble(QString key, double value)
{
    m_jsonObj.insert(key, QJsonValue(value));
    FINE_DEBUG_OUTPUT("[Json Operation]Set double for key: " + key);
}

void JsonOperation::setBool(QString key, bool value)
{
    m_jsonObj.insert(key, QJsonValue(value));
    FINE_DEBUG_OUTPUT("[Json Operation]Set bool for key: " + key);
}

void JsonOperation::setJson(QString key, const JsonOperation& jsonObj)
{
    m_jsonObj.insert(key, jsonObj.m_jsonObj);
    FINE_DEBUG_OUTPUT("[Json Operation]Set JSON object for key: " + key);
}

void JsonOperation::setJsonObject(QString key, const QJsonObject& jsonObj)
{
    m_jsonObj.insert(key, jsonObj);
    FINE_DEBUG_OUTPUT("[Json Operation]Set JSON object for key: " + key);
}

bool JsonOperation::setIntInJson(QString jsonKey, QString valueKey, int value)
{
    if (!m_jsonObj.contains(jsonKey)) {
        ERROR_DEBUG_OUTPUT("[Json Operation]Key not found:" + jsonKey);
        return false;
    }

    QJsonValue target = m_jsonObj[jsonKey];
    if (!target.isObject()) {
        ERROR_DEBUG_OUTPUT("[Json Operation]Target is not a JSON object:" + jsonKey);
        return false;
    }

    QJsonObject targetObj = target.toObject();
    targetObj.insert(valueKey, value);
    m_jsonObj.insert(jsonKey, targetObj);

    return true;
}

bool JsonOperation::setDoubleInJson(QString jsonKey, QString valueKey, double value)
{
    if (!m_jsonObj.contains(jsonKey)) {
        ERROR_DEBUG_OUTPUT("[Json Operation]Key not found:" + jsonKey);
        return false;
    }

    QJsonValue target = m_jsonObj[jsonKey];
    if (!target.isObject()) {
        ERROR_DEBUG_OUTPUT("[Json Operation]Target is not a JSON object:" + jsonKey);
        return false;
    }

    QJsonObject targetObj = target.toObject();
    targetObj.insert(valueKey, value);
    m_jsonObj.insert(jsonKey, targetObj);

    return true;
}

bool JsonOperation::setStringInJson(QString jsonKey, QString valueKey, QString value)
{
    if (!m_jsonObj.contains(jsonKey)) {
        ERROR_DEBUG_OUTPUT("[Json Operation]Key not found:" + jsonKey);
        return false;
    }

    QJsonValue target = m_jsonObj[jsonKey];
    if (!target.isObject()) {
        ERROR_DEBUG_OUTPUT("[Json Operation]Target is not a JSON object:" + jsonKey);
        return false;
    }

    QJsonObject targetObj = target.toObject();
    targetObj.insert(valueKey, value);
    m_jsonObj.insert(jsonKey, targetObj);

    return true;
}

bool JsonOperation::setBoolInJson(QString jsonKey, QString valueKey, bool value)
{
    if (!m_jsonObj.contains(jsonKey)) {
        ERROR_DEBUG_OUTPUT("[Json Operation]Key not found:" + jsonKey);
        return false;
    }

    QJsonValue target = m_jsonObj[jsonKey];
    if (!target.isObject()) {
        ERROR_DEBUG_OUTPUT("[Json Operation]Target is not a JSON object:" + jsonKey);
        return false;
    }

    QJsonObject targetObj = target.toObject();
    targetObj.insert(valueKey, value);
    m_jsonObj.insert(jsonKey, targetObj);

    return true;
}

bool JsonOperation::save() const
{
	if (m_filePath.isEmpty()) {
		ERROR_DEBUG_OUTPUT("[Json Operation]No file path to save");
		return false;
	}
	QFile file(m_filePath);
	if (!file.open(QIODevice::WriteOnly | QIODevice::Text | QIODevice::Truncate)) {
		ERROR_DEBUG_OUTPUT("[Json Operation]Failed to save file: " + m_filePath);
		return false;
	}
	const QJsonDocument doc(m_jsonObj);
	file.write(doc.toJson(QJsonDocument::Indented));
	file.close();
	FINE_DEBUG_OUTPUT("[Json Operation]Saved file: " + m_filePath);
	return true;
}
