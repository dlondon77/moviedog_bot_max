    async def _run_slides_generation(self, event, user_id: int):
        context = self._get_user_context(user_id)
        context['slide_state'] = None

        await event.message.answer("🎨 Генерирую слайды... Это может занять 20–40 секунд.")

        try:
            proc = subprocess.run(
                [
                    SLIDES_PYTHON, SLIDES_RUNNER,
                    "--rubric", context.get('slide_rubric', ''),
                    "--input", SLIDES_INPUT,
                    "--output", SLIDES_OUTPUT,
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=SLIDES_DIR,
            )
        except subprocess.TimeoutExpired:
            await event.message.answer("🐾 Генерация затянулась. Попробуй позже.")
            return
        except Exception as e:
            logger.error(f"Ошибка запуска run_slides: {e}")
            await event.message.answer("🐾 Не смогла запустить генератор. Проверь логи.")
            return

        stdout = proc.stdout.strip()
        try:
            result = json.loads(stdout)
        except Exception:
            logger.error(f"Невалидный JSON:\nstdout={stdout}\nstderr={proc.stderr}")
            await event.message.answer("🐾 Генератор вернул неожиданный ответ. Проверь логи.")
            return

        if not result.get("ok"):
            await event.message.answer(
                f"❌ Ошибка: {result.get('error', 'неизвестно')}",
                attachments=[get_main_menu()]
            )
            return

        files = result.get("files", [])
        if not files:
            await event.message.answer("🐾 Генератор не вернул файлов. Проверь логи.")
            return

        # === 1. Собираем ZIP ===
        zip_name = "slides.zip"
        zip_path = os.path.join(SLIDES_OUTPUT, zip_name)

        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for name in files:
                    file_path = os.path.join(SLIDES_OUTPUT, name)
                    if os.path.exists(file_path):
                        zf.write(file_path, arcname=name)
            logger.info(f"✅ ZIP собран: {zip_path}")
        except Exception as e:
            logger.error(f"Ошибка сборки ZIP: {e}")
            zip_path = None

        # === 2. Пробуем отправить ZIP в чат (не падаем при ошибке) ===
        zip_sent = False
        if zip_path and os.path.exists(zip_path):
            try:
                await self._send_document(event, zip_path)
                zip_sent = True
                logger.info("✅ ZIP отправлен в чат")
            except Exception as e:
                logger.warning(f"⚠️ Не смогла отправить ZIP в чат: {e}")

        # === 3. Финальное сообщение + ссылка на архив ===
        download_url = (
            "https://bothost.ru/file-manager.php"
            "?bot=bot_1790103008_5442_dimamuffin"
            "&download=%2Fapp%2Fslides%2Foutput%2Fslides.zip"
        )

        buttons = [
            [{"type": "callback", "text": "🎨 Слайды", "payload": "slides_menu"}],
            [{"type": "callback", "text": "🏠 В главное меню", "payload": "back_to_menu"}],
        ]
        keyboard = InlineKeyboardMarkup(buttons)

        if zip_sent:
            text = (
                "🎉 <b>Готово!</b>\n\n"
                "📦 Архив <b>slides.zip</b> отправлен выше.\n"
                f"📂 <a href='{download_url}'>Скачать архив</a>\n\n"
                "💡 Внутри: card_1..5.html, post.txt, post.html. "
                "Открой HTML в браузере и сделай скриншот через DevTools → Capture node screenshot."
            )
        else:
            text = (
                "🎉 <b>Готово!</b>\n\n"
                f"📂 <a href='{download_url}'>Скачать slides.zip</a>\n\n"
                "💡 Внутри: card_1..5.html, post.txt, post.html. "
                "Открой HTML в браузере и сделай скриншот через DevTools → Capture node screenshot."
            )

        await event.message.answer(
            text,
            parse_mode="html",
            attachments=[keyboard],
        )
