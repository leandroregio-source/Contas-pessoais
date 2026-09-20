"""Extração de texto do PDF da fatura.

A fatura do Itaú é PDF de texto, não digitalização — dá para ler direto, sem
OCR e sem IA. Só a foto de recibo precisa de visão.
"""
from __future__ import annotations

import io


class PDFIlegivel(RuntimeError):
    pass


def extrair_texto(pdf_bytes: bytes, senha: str | None = None) -> str:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover
        raise PDFIlegivel(
            "pdfplumber não instalado — rode: pip install -r requirements.txt"
        ) from exc

    partes: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes), password=senha or "") as pdf:
            for pagina in pdf.pages:
                texto = pagina.extract_text(x_tolerance=1.5, y_tolerance=3) or ""
                if texto.strip():
                    partes.append(texto)
    except Exception as exc:  # noqa: BLE001 - PDF protegido/corrompido vira mensagem
        raise PDFIlegivel(f"Não consegui ler o PDF: {exc}") from exc

    texto = "\n".join(partes)
    if len(texto.strip()) < 50:
        raise PDFIlegivel(
            "O PDF não tem texto extraível (parece ser digitalizado). "
            "Baixe a fatura em PDF pelo app do Itaú, não uma foto dela."
        )
    return texto
