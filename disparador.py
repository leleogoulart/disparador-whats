"""Fila de mensagens para WhatsApp Web, com uma única guia do Chrome."""

import csv
from pathlib import Path
from queue import Empty, Queue
import random
import re
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from urllib.parse import urlencode

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException, StaleElementReferenceException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait


class Pausado(Exception):
    pass


class EnvioIncerto(Exception):
    """O clique pode ter ocorrido; nunca repetir automaticamente."""


def normalizar_numeros(texto):
    """Exige DDI explícito; aceita formatação, remove duplicados e rejeita lixo."""
    numeros, vistos = [], set()
    for linha, bruto in enumerate(texto.splitlines(), 1):
        bruto = bruto.strip()
        if not bruto:
            continue
        if not re.fullmatch(r"\+?[0-9\s().-]+", bruto):
            raise ValueError(f"Linha {linha}: use apenas o número com DDI e DDD.")
        numero = re.sub(r"\D", "", bruto)
        if not re.fullmatch(r"[1-9][0-9]{7,14}", numero):
            raise ValueError(f"Linha {linha}: número inválido (8 a 15 dígitos, com DDI).")
        if numero not in vistos:
            numeros.append(numero)
            vistos.add(numero)
    if not numeros:
        raise ValueError("Preencha ao menos um número com DDI e DDD.")
    return numeros


def url_conversa(numero):
    return "https://web.whatsapp.com/send?" + urlencode({"phone": numero})


class WhatsAppBot:
    def __init__(self, root):
        self.root = root
        root.title("WhatsApp Comercial — uma única guia")
        root.geometry("640x800")
        self.driver = None
        self.whatsapp_handle = None
        self.worker = None
        self.stop_event = threading.Event()
        self.eventos = Queue()
        self.fechando = False
        self.lista_numeros = []
        self.current_index = 0
        self.resultados = []
        self.caminho_imagem = None
        self.mensagem = ""
        self.delay_min, self.delay_max = 45, 90
        self._setup_ui()
        root.protocol("WM_DELETE_WINDOW", self.fechar)
        root.after(100, self._processar_eventos)

    def _setup_ui(self):
        area = tk.Frame(self.root, padx=18, pady=12)
        area.pack(fill="both", expand=True)
        tk.Label(area, text="Representantes: DDI + DDD + número, um por linha").pack(anchor="w")
        self.txt_numeros = scrolledtext.ScrolledText(area, height=7, wrap="word")
        self.txt_numeros.pack(fill="x", pady=(4, 10))
        tk.Label(area, text="Mensagem:").pack(anchor="w")
        self.txt_mensagem = scrolledtext.ScrolledText(area, height=7, wrap="word")
        self.txt_mensagem.pack(fill="x", pady=(4, 10))
        delays = tk.Frame(area)
        delays.pack(anchor="w")
        tk.Label(delays, text="Intervalo mínimo (s):").pack(side="left")
        self.entry_delay_min = tk.Entry(delays, width=6)
        self.entry_delay_min.insert(0, "45")
        self.entry_delay_min.pack(side="left", padx=5)
        tk.Label(delays, text="Máximo (s):").pack(side="left")
        self.entry_delay_max = tk.Entry(delays, width=6)
        self.entry_delay_max.insert(0, "90")
        self.entry_delay_max.pack(side="left", padx=5)
        anexos = tk.Frame(area)
        anexos.pack(fill="x", pady=12)
        self.btn_anexo = tk.Button(anexos, text="Anexar imagem", command=self.anexar_imagem)
        self.btn_anexo.pack(side="left")
        self.btn_remover = tk.Button(anexos, text="Remover", command=self.remover_imagem)
        self.btn_remover.pack(side="left", padx=5)
        self.lbl_anexo = tk.Label(area, text="Nenhuma imagem selecionada", anchor="w")
        self.lbl_anexo.pack(fill="x")
        self.lbl_progresso = tk.Label(area, text="Processados: 0/0")
        self.lbl_progresso.pack(pady=(12, 4))
        self.lbl_status = tk.Label(area, text="Pronto para iniciar.", wraplength=590, fg="blue")
        self.lbl_status.pack(fill="x", pady=5)
        botoes = tk.Frame(area)
        botoes.pack(pady=8)
        self.btn_play = tk.Button(botoes, text="Iniciar / Continuar", command=self.iniciar_disparo)
        self.btn_play.pack(side="left", padx=5)
        self.btn_stop = tk.Button(botoes, text="Pausar", command=self.parar_disparo, state="disabled")
        self.btn_stop.pack(side="left", padx=5)
        self.btn_reset = tk.Button(botoes, text="Nova fila", command=self.reiniciar_fila)
        self.btn_reset.pack(side="left", padx=5)
        tk.Button(area, text="Exportar resultados (CSV)", command=self.exportar).pack()
        self.log = scrolledtext.ScrolledText(area, height=8, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, pady=(10, 0))
        self.editaveis = [self.txt_numeros, self.txt_mensagem, self.entry_delay_min,
                          self.entry_delay_max, self.btn_anexo, self.btn_remover]

    def ocupado(self):
        # O worker só é liberado após a interface consumir todos os resultados.
        return self.worker is not None

    def _registrar(self, texto):
        self.log.config(state="normal")
        self.log.insert("end", texto + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _processar_eventos(self):
        # Só o thread principal acessa Tkinter, inclusive root.after().
        encerrado = self.worker is not None and not self.worker.is_alive()
        try:
            while True:
                tipo, valor = self.eventos.get_nowait()
                if tipo == "status":
                    self.lbl_status.config(text=valor)
                elif tipo == "log":
                    self._registrar(valor)
                elif tipo == "resultado":
                    self.resultados.append(valor)
                    self.current_index += 1
                    self.lbl_progresso.config(
                        text=f"Processados: {self.current_index}/{len(self.lista_numeros)}")
                elif tipo == "erro":
                    messagebox.showerror("Execução interrompida", valor)
        except Empty:
            pass
        if encerrado:
            self.worker = None
        ativa = self.ocupado()
        self.btn_play.config(state="disabled" if ativa or self.fechando else "normal")
        self.btn_stop.config(state="normal" if ativa and not self.stop_event.is_set() else "disabled")
        self.btn_reset.config(state="disabled" if ativa else "normal")
        for widget in self.editaveis:
            widget.config(state="disabled" if ativa or self.lista_numeros else "normal")
        if self.fechando and not ativa:
            # Encerramento também é executado fora do thread da interface.
            if self.driver is not None:
                self.worker = threading.Thread(target=self._encerrar_navegador, daemon=True)
                self.worker.start()
            else:
                self.root.destroy()
                return
        self.root.after(100, self._processar_eventos)

    def anexar_imagem(self):
        caminho = filedialog.askopenfilename(filetypes=[("Imagens", "*.png *.jpg *.jpeg")])
        if caminho:
            self.caminho_imagem = str(Path(caminho).resolve())
            self.lbl_anexo.config(text=Path(caminho).name)

    def remover_imagem(self):
        self.caminho_imagem = None
        self.lbl_anexo.config(text="Nenhuma imagem selecionada")

    def iniciar_disparo(self):
        if self.ocupado() or self.fechando:
            return
        if self.lista_numeros and self.current_index >= len(self.lista_numeros):
            messagebox.showinfo("Fila finalizada", "Use Nova fila para preparar outro envio.")
            return
        if not self.lista_numeros:
            try:
                numeros = normalizar_numeros(self.txt_numeros.get("1.0", "end"))
                mensagem = self.txt_mensagem.get("1.0", "end-1c")
                minimo, maximo = int(self.entry_delay_min.get()), int(self.entry_delay_max.get())
                if not mensagem.strip():
                    raise ValueError("Preencha a mensagem.")
                if minimo < 1 or maximo < minimo:
                    raise ValueError("Use intervalos positivos; máximo deve ser maior ou igual ao mínimo.")
                if self.caminho_imagem and not Path(self.caminho_imagem).is_file():
                    raise ValueError("A imagem selecionada não está disponível.")
            except ValueError as erro:
                messagebox.showwarning("Confira os dados", str(erro))
                return
            self.lista_numeros, self.mensagem = numeros, mensagem
            self.delay_min, self.delay_max = minimo, maximo
        self.stop_event.clear()
        # Índice capturado no thread da interface; o worker usa sua própria cópia.
        inicio = self.current_index
        self.worker = threading.Thread(target=self.processo_envio, args=(inicio,), daemon=True)
        self.worker.start()
        self.btn_play.config(state="disabled")

    def parar_disparo(self):
        self.stop_event.set()
        self.lbl_status.config(text="Pausando; aguardando a operação em andamento terminar…")
        self.btn_stop.config(state="disabled")

    def reiniciar_fila(self):
        if self.ocupado():
            return
        self.lista_numeros = []
        self.current_index = 0
        self.resultados = []
        self.lbl_progresso.config(text="Processados: 0/0")
        self.lbl_status.config(text="Nova fila. Você pode editar os dados.")

    def exportar(self):
        destino = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not destino:
            return
        try:
            with open(destino, "w", newline="", encoding="utf-8-sig") as arquivo:
                writer = csv.writer(arquivo, delimiter=";")
                writer.writerow(["numero", "status", "detalhe"])
                for numero, status, detalhe in self.resultados:
                    # Impede fórmulas ao abrir o relatório em uma planilha.
                    seguro = lambda v: "'" + v if v.startswith(("=", "+", "-", "@")) else v
                    writer.writerow([seguro(v) for v in (numero, status, detalhe)])
        except OSError as erro:
            messagebox.showerror("Erro ao exportar", str(erro))

    def _checar_pausa(self):
        if self.stop_event.is_set():
            raise Pausado()

    def _aguardar(self, condicao, segundos=30, cancelavel=True):
        def consultar(driver):
            if cancelavel:
                self._checar_pausa()
            return condicao(driver)
        return WebDriverWait(self.driver, segundos, poll_frequency=0.3,
                             ignored_exceptions=(NoSuchElementException, StaleElementReferenceException)).until(consultar)

    def inicializar_navegador(self):
        if self.driver is None:
            self.eventos.put(("status", "Abrindo Chrome. Escaneie o QR Code se necessário."))
            options = webdriver.ChromeOptions()
            perfil = Path(__file__).resolve().parent / "sessao_whatsapp"
            options.add_argument(f"--user-data-dir={perfil}")
            self.driver = webdriver.Chrome(options=options)
            self.driver.set_page_load_timeout(45)
            self.whatsapp_handle = self.driver.current_window_handle
            self.driver.get("https://web.whatsapp.com")
        else:
            # Não segue abas de links externos ou usa window.open().
            self.driver.switch_to.window(self.whatsapp_handle)
        self._aguardar(lambda d: d.find_element(By.ID, "side"), 120)

    def abrir_conversa(self, numero):
        self._checar_pausa()
        self.driver.switch_to.window(self.whatsapp_handle)
        # get() navega na guia atual: elimina wa.me, pop-ups e links intermediários.
        self.driver.get(url_conversa(numero))

        def conversa_pronta(driver):
            for modal in driver.find_elements(By.CSS_SELECTOR, '[role="dialog"], [data-animate-modal-popup="true"]'):
                texto = modal.text.lower()
                if any(t in texto for t in ("inválido", "invalid", "não está no whatsapp", "isn't on whatsapp")):
                    raise ValueError("Número inválido ou sem WhatsApp.")
            caixas = driver.find_elements(By.CSS_SELECTOR, '#main footer [contenteditable="true"][role="textbox"]')
            return next((e for e in caixas if e.is_displayed()), False)
        return self._aguardar(conversa_pronta, 45)

    @staticmethod
    def _digitar_texto(elemento, texto):
        # Um rascunho de uma execução pausada não pode duplicar a mensagem.
        elemento.click()
        elemento.send_keys(Keys.CONTROL, "a")
        elemento.send_keys(Keys.BACKSPACE)
        linhas = texto.split("\n")
        for indice, linha in enumerate(linhas):
            if linha:
                elemento.send_keys(linha)
            if indice < len(linhas) - 1:
                elemento.send_keys(Keys.SHIFT, Keys.ENTER)

    def _bolhas_saida(self):
        # Leitura do DOM público; não acessa APIs internas nem injeta scripts.
        return self.driver.find_elements(By.CSS_SELECTOR, '#main .message-out')

    def _ids_saida(self):
        return {e.get_attribute("data-id") for e in self.driver.find_elements(
            By.CSS_SELECTOR, '#main [data-id]') if e.find_elements(By.CSS_SELECTOR, '.message-out')}

    def enviar_mensagem_para(self, numero):
        caixa = self.abrir_conversa(numero)
        if self.caminho_imagem:
            def clipe(driver):
                elementos = driver.find_elements(By.CSS_SELECTOR,
                    '#main [data-icon="attach-menu-plus"], #main [data-icon="plus-rounded"], #main [data-icon="clip"]')
                return next((e for e in elementos if e.is_displayed() and e.is_enabled()), False)
            self._aguardar(clipe, 15).click()
            campo = self._aguardar(lambda d: d.find_element(By.CSS_SELECTOR, 'input[type="file"][accept*="image"]'), 15)
            campo.send_keys(self.caminho_imagem)
            def legenda(driver):
                campos = driver.find_elements(By.CSS_SELECTOR,
                    '[contenteditable="true"][aria-label="Adicionar legenda"], '
                    '[contenteditable="true"][aria-label="Add a caption"]')
                return next((e for e in campos if e.is_displayed()), False)
            caixa = self._aguardar(legenda, 20)
        self._digitar_texto(caixa, self.mensagem)
        self._checar_pausa()
        ids_antes = self._ids_saida()
        quantidade_antes = len(self._bolhas_saida())
        # A partir deste ponto, qualquer exceção é incerta: não repetir o envio.
        try:
            if self.caminho_imagem:
                def enviar_visivel(driver):
                    botoes = driver.find_elements(By.CSS_SELECTOR, '[data-icon="send"]')
                    return next((e for e in botoes if e.is_displayed() and e.is_enabled()), False)
                self._aguardar(enviar_visivel, 15).click()
            else:
                caixa.send_keys(Keys.ENTER)
            # Confirma apenas que apareceu uma saída local. Não garante entrega/leitura.
            def saida_local(driver):
                return bool(self._ids_saida() - ids_antes) or len(self._bolhas_saida()) > quantidade_antes
            self._aguardar(saida_local, 20, cancelavel=False)
        except Exception as erro:
            raise EnvioIncerto("Não foi possível confirmar a saída local; confira a conversa antes de repetir.") from erro

    def processo_envio(self, inicio):
        indice = inicio
        try:
            self.inicializar_navegador()
            while indice < len(self.lista_numeros):
                self._checar_pausa()
                numero = self.lista_numeros[indice]
                self.eventos.put(("status", f"Preparando mensagem para {numero}…"))
                interromper = False
                try:
                    self.enviar_mensagem_para(numero)
                    status, detalhe = "saida_local", "Mensagem apareceu na conversa; entrega não verificada."
                except Pausado:
                    raise
                except EnvioIncerto as erro:
                    status, detalhe = "incerto", str(erro)
                    interromper = True
                except Exception as erro:
                    descricao = str(erro).strip() or "Erro sem detalhes."
                    status, detalhe = "falha", f"{type(erro).__name__}: {descricao.splitlines()[0]}"
                    # Evita avançar a fila inteira se a sessão ou os seletores falharem.
                    interromper = True
                self.eventos.put(("resultado", (numero, status, detalhe)))
                self.eventos.put(("log", f"{numero} — {status}: {detalhe}"))
                indice += 1
                if interromper:
                    self.eventos.put(("status", "Fila interrompida. Confira o resultado antes de continuar."))
                    return
                if indice < len(self.lista_numeros):
                    self._intervalo(random.randint(self.delay_min, self.delay_max))
            self.eventos.put(("status", "Fila processada. Confira os resultados; entrega não verificada."))
        except Pausado:
            self.eventos.put(("status", "Pausado. Continuar retoma os contatos pendentes."))
        except Exception as erro:
            self.eventos.put(("erro", str(erro)))
            self.eventos.put(("status", "Execução interrompida. Confira o Chrome e tente continuar."))

    def _intervalo(self, segundos):
        prazo = time.monotonic() + segundos
        while time.monotonic() < prazo:
            self._checar_pausa()
            restante = max(1, int(prazo - time.monotonic() + 0.999))
            self.eventos.put(("status", f"Próximo contato em {restante}s…"))
            self.stop_event.wait(min(1, max(0, prazo - time.monotonic())))

    def fechar(self):
        self.fechando = True
        self.stop_event.set()
        self.lbl_status.config(text="Encerrando após a operação em andamento…")

    def _encerrar_navegador(self):
        try:
            self.driver.quit()
        finally:
            self.driver = None


if __name__ == "__main__":
    janela = tk.Tk()
    WhatsAppBot(janela)
    janela.mainloop()
