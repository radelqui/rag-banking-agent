from app.security.pii import StreamMasker, mask_pii


def test_masks_iban_dni_card_email():
    text = "IBAN ES91 2100 0418 4502 0005 1332, DNI 12345678Z, tarjeta 4111 1111 1111 1111, mail a@b.com"
    out = mask_pii(text)
    assert "[IBAN]" in out and "[DNI]" in out and "[TARJETA]" in out and "[EMAIL]" in out
    assert "ES91" not in out and "12345678Z" not in out and "a@b.com" not in out


def test_leaves_normal_text():
    assert mask_pii("La tasa es 3,5% anual") == "La tasa es 3,5% anual"


def test_stream_masker_catches_entity_split_across_tokens():
    m = StreamMasker()
    out = "".join(m.feed(t) for t in ["Tu DNI es 1234", "5678Z y tu mail", " a@b.com. Fin"])
    out += m.flush()
    assert out == "Tu DNI es [DNI] y tu mail [EMAIL] Fin"


def test_stream_masker_emits_progressively_on_long_text():
    m = StreamMasker(max_buffer=60)
    emitted = m.feed("palabra " * 12)  # 96 chars sin punto: debe emitir parte y retener cola
    assert emitted and len(emitted) < 96
