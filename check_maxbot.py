# check_maxbot.py
import maxbot
import inspect

print("=== maxbot version ===")
print(maxbot.__version__ if hasattr(maxbot, '__version__') else 'unknown')

print("\n=== Содержимое maxbot ===")
print(dir(maxbot))

try:
    from maxbot import Bot
    print("\n✅ Bot импортируется из maxbot")
except ImportError as e:
    print(f"\n❌ Bot не импортируется из maxbot: {e}")

try:
    from maxbot.bot import Bot
    print("✅ Bot импортируется из maxbot.bot")
except ImportError as e:
    print(f"❌ Bot не импортируется из maxbot.bot: {e}")

try:
    from maxbot import Dispatcher
    print("✅ Dispatcher импортируется из maxbot")
except ImportError as e:
    print(f"❌ Dispatcher не импортируется из maxbot: {e}")

print("\n=== Всё содержимое maxbot (рекурсивно) ===")
for name in dir(maxbot):
    if not name.startswith('_'):
        print(f"  {name}")
        try:
            module = getattr(maxbot, name)
            if hasattr(module, '__dict__'):
                for subname in dir(module):
                    if not subname.startswith('_'):
                        print(f"    - {subname}")
        except:
            pass
