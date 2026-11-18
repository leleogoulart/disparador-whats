"""Testes sem login, Chrome ou envio real de mensagens."""
import threading
import unittest
from queue import Queue
from unittest.mock import MagicMock

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys

from disparador import WhatsAppBot, Pausado, EnvioIncerto, normalizar_numeros, url_conversa


def bot_sem_interface():
    bot = WhatsAppBot.__new__(WhatsAppBot)
    bot.stop_event = threading.Event()
    bot.eventos = Queue()
    bot.driver = MagicMock()
    bot.whatsapp_handle = "guia-original"
    bot.caminho_imagem = None
    bot.mensagem = "Olá\nComo vai?"
    bot.lista_numeros = ["5511999990000", "5511988880000"]
    bot.delay_min = bot.delay_max = 1
    bot.worker = None
    return bot


class ValidacaoTest(unittest.TestCase):
    def test_normaliza_e_remove_duplicados_preservando_ordem(self):
        self.assertEqual(normalizar_numeros(
            "+55 (11) 99999-0000\n5511999990000\n\n+55 11 98888-0000"),
            ["5511999990000", "5511988880000"])

    def test_rejeita_linhas_malformadas(self):
        for entrada in ("", "01199999999", "123", "55abc11999990000",
                        "5511999990000,5511988880000", "1234567890123456"):
            with self.subTest(entrada=entrada), self.assertRaises(ValueError):
                normalizar_numeros(entrada)


class NavegacaoTest(unittest.TestCase):
    def test_usa_rota_web_na_guia_original(self):
        bot = bot_sem_interface()
        bot._aguardar = MagicMock()
        bot.abrir_conversa("5511999990000")
        bot.driver.switch_to.window.assert_called_once_with("guia-original")
        bot.driver.get.assert_called_once_with(url_conversa("5511999990000"))
        bot.driver.switch_to.new_window.assert_not_called()
        bot.driver.execute_script.assert_not_called()

    def test_pausa_impede_navegacao(self):
        bot = bot_sem_interface()
        bot.stop_event.set()
        with self.assertRaises(Pausado):
            bot.abrir_conversa("5511999990000")
        bot.driver.get.assert_not_called()

    def test_substitui_rascunho_e_preserva_quebra_de_linha(self):
        campo = MagicMock()
        WhatsAppBot._digitar_texto(campo, "Olá\nComo vai?")
        chamadas = [c.args for c in campo.send_keys.call_args_list]
        self.assertEqual(chamadas, [(Keys.CONTROL, "a"), (Keys.BACKSPACE,),
                                   ("Olá",), (Keys.SHIFT, Keys.ENTER), ("Como vai?",)])

    def test_timeout_apos_enter_e_incerto_e_nao_repete(self):
        bot = bot_sem_interface()
        bot.abrir_conversa = MagicMock()
        campo = bot.abrir_conversa.return_value
        bot._ids_saida = MagicMock(return_value=set())
        bot._bolhas_saida = MagicMock(return_value=[])
        bot._aguardar = MagicMock(side_effect=TimeoutException())
        with self.assertRaises(EnvioIncerto):
            bot.enviar_mensagem_para("5511999990000")
        enters = [c for c in campo.send_keys.call_args_list if c.args == (Keys.ENTER,)]
        self.assertEqual(len(enters), 1)

    def test_worker_finalizado_ainda_bloqueia_reinicio_ate_drenar_resultados(self):
        bot = bot_sem_interface()
        bot.worker = MagicMock()
        bot.worker.is_alive.return_value = False
        self.assertTrue(bot.ocupado())


class FilaTest(unittest.TestCase):
    def executar(self, erro=None, inicio=0):
        bot = bot_sem_interface()
        bot.inicializar_navegador = MagicMock()
        bot.enviar_mensagem_para = MagicMock(side_effect=erro)
        bot._intervalo = MagicMock()
        bot.processo_envio(inicio)
        eventos = list(bot.eventos.queue)
        resultados = [v for tipo, v in eventos if tipo == "resultado"]
        return bot, resultados

    def test_sucesso_processa_cada_numero_uma_vez(self):
        bot, resultados = self.executar()
        self.assertEqual(bot.enviar_mensagem_para.call_count, 2)
        self.assertEqual([r[1] for r in resultados], ["saida_local", "saida_local"])
        bot._intervalo.assert_called_once_with(1)

    def test_falha_interrompe_sem_tentar_os_demais(self):
        bot, resultados = self.executar(ValueError("Número inválido"))
        self.assertEqual(bot.enviar_mensagem_para.call_count, 1)
        self.assertEqual(resultados[0][1], "falha")

    def test_incerto_interrompe_sem_reenvio(self):
        bot, resultados = self.executar(EnvioIncerto("Conferir conversa"))
        self.assertEqual(bot.enviar_mensagem_para.call_count, 1)
        self.assertEqual(resultados[0][1], "incerto")

    def test_pausa_nao_consume_contato_pendente(self):
        bot, resultados = self.executar(Pausado())
        self.assertEqual(resultados, [])
        self.assertEqual(bot.enviar_mensagem_para.call_count, 1)

    def test_retomada_usa_indice_pendente(self):
        bot, resultados = self.executar(inicio=1)
        bot.enviar_mensagem_para.assert_called_once_with("5511988880000")
        self.assertEqual(len(resultados), 1)

    def test_pausa_interrompe_intervalo_imediatamente(self):
        bot = bot_sem_interface()
        bot.stop_event.set()
        with self.assertRaises(Pausado):
            bot._intervalo(90)


if __name__ == "__main__":
    unittest.main()
