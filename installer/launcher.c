/*
 * Mirage.exe
 *
 * Starts Mirage with the private Python that sits next to this file, so Windows, the taskbar and Task Manager
 * all see "Mirage" (with its icon) instead of Python. It never touches any Python you installed yourself:
 * Mirage runs in isolated mode (-I).
 *
 *   Mirage.exe [--tray] [...]      start Mirage (runs app\mirage_app.py)
 *   Mirage.exe -m pip ...          anything that looks like a Python option or a .py file is passed straight
 *                                  to Python, so Mirage.exe can stand in for python.exe when it has to
 */
#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <shellapi.h>
#include <stdlib.h>
#include <wchar.h>
#include <Python.h>

static int is_python_option(const wchar_t *a)
{
    size_t n;
    if (!a || !a[0])
        return 0;
    if (a[0] == L'-' && a[1] != L'-' && a[1] != 0)   /* -m, -c, -I, -u ... (Mirage's own options use --) */
        return 1;
    n = wcslen(a);
    return n > 3 && _wcsicmp(a + n - 3, L".py") == 0;  /* a script */
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmdline, int show)
{
    int argc = 0, i, n = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    static wchar_t exe[32768], script[32768];
    wchar_t *slash, **args;
    (void)inst; (void)prev; (void)cmdline; (void)show;

    if (!argv)
        return 1;
    if (!GetModuleFileNameW(NULL, exe, 32768))
        return 1;
    wcscpy_s(script, 32768, exe);
    slash = wcsrchr(script, L'\\');
    if (slash)
        slash[1] = 0;
    wcscat_s(script, 32768, L"app\\mirage_app.py");

    args = (wchar_t **)calloc((size_t)argc + 3, sizeof(wchar_t *));
    if (!args)
        return 1;
    args[n++] = exe;
    if (argc > 1 && is_python_option(argv[1])) {
        for (i = 1; i < argc; i++)
            args[n++] = argv[i];
    } else {
        if (GetFileAttributesW(script) == INVALID_FILE_ATTRIBUTES) {
            MessageBoxW(NULL, L"Mirage's files are missing. Please reinstall Mirage.", L"Mirage", MB_ICONERROR);
            return 1;
        }
        args[n++] = L"-I";  /* isolated: ignore other Pythons' settings and packages */
        args[n++] = script;
        for (i = 1; i < argc; i++)
            args[n++] = argv[i];
    }
    return Py_Main(n, args);
}
