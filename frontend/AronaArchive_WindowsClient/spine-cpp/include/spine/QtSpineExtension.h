#ifndef Qt_Spine_Extension_H
#define Qt_Spine_Extension_H

#include <spine/Extension.h>
#include <spine/SpineString.h>

#include <QDebug>
#include <QString>
#include <QByteArray>
#include <QFile>

class SP_API QtSpineExtension : public spine::SpineExtension {
public:
	// 构造函数
	QtSpineExtension();

	// 虚析构函数
	virtual ~QtSpineExtension() override;

protected:
	// 内存管理
	virtual void* _alloc(size_t size, const char* file, int line) override;

	virtual void* _calloc(size_t size, const char* file, int line) override;

	virtual void* _realloc(void* ptr, size_t size, const char* file, int line) override;

	virtual void _free(void* mem, const char* file, int line) override;

	// 文件读取
	virtual char* _readFile(const spine::String& path, int* length) override;
};

// 外部函数getDefaultExtension()
extern "C" SP_API spine::SpineExtension* getDefaultExtension();

#endif // !Qt_Spine_Extension_H
