"""
Validadores compartilhados para o sistema de entregas
Inclui validação de coordenadas geográficas e outras validações comuns
"""

from typing import Tuple, Optional

# Import condicional para funcionar em testes standalone
try:
    from shared.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


def validate_coordinates(
    latitude: Optional[float],
    longitude: Optional[float],
    strict: bool = False
) -> Tuple[bool, Optional[str]]:
    """
    Valida se as coordenadas geográficas são válidas
    
    Args:
        latitude: Latitude a ser validada (-90 a 90)
        longitude: Longitude a ser validada (-180 a 180)
        strict: Se True, valida também se está dentro do Brasil
    
    Returns:
        Tupla (is_valid, error_message)
        - is_valid: True se coordenadas válidas
        - error_message: Mensagem de erro descritiva (None se válido)
    
    Examples:
        >>> validate_coordinates(-22.9068, -43.1729)  # Rio de Janeiro
        (True, None)
        
        >>> validate_coordinates(100, 200)  # Inválido
        (False, "Latitude deve estar entre -90 e 90")
        
        >>> validate_coordinates(40.7128, -74.0060, strict=True)  # NY (fora do Brasil)
        (False, "Coordenadas fora do território brasileiro")
    """
    
    # Verifica se coordenadas foram fornecidas
    if latitude is None or longitude is None:
        return True, None  # Coordenadas opcionais são válidas quando None
    
    # Validação básica de range
    if not isinstance(latitude, (int, float)):
        return False, f"Latitude deve ser número, recebido: {type(latitude).__name__}"
    
    if not isinstance(longitude, (int, float)):
        return False, f"Longitude deve ser número, recebido: {type(longitude).__name__}"
    
    if not (-90 <= latitude <= 90):
        return False, f"Latitude deve estar entre -90 e 90, recebido: {latitude}"
    
    if not (-180 <= longitude <= 180):
        return False, f"Longitude deve estar entre -180 e 180, recebido: {longitude}"
    
    # Validação estrita: verifica se está no Brasil
    if strict:
        is_brazil, brazil_error = is_valid_brazil_coordinates(latitude, longitude)
        if not is_brazil:
            return False, brazil_error
    
    return True, None


def is_valid_brazil_coordinates(latitude: float, longitude: float) -> Tuple[bool, Optional[str]]:
    """
    Verifica se as coordenadas estão dentro do território brasileiro
    
    Bounding box aproximada do Brasil:
    - Latitude: -33.75 (sul) a 5.27 (norte)
    - Longitude: -73.99 (oeste) a -32.39 (leste)
    
    Args:
        latitude: Latitude a verificar
        longitude: Longitude a verificar
    
    Returns:
        Tupla (is_valid, error_message)
    
    Examples:
        >>> is_valid_brazil_coordinates(-22.9068, -43.1729)  # Rio
        (True, None)
        
        >>> is_valid_brazil_coordinates(40.7128, -74.0060)  # Nova York
        (False, "Coordenadas fora do território brasileiro")
    """
    
    # Bounding box do Brasil (com margem de segurança)
    LAT_MIN, LAT_MAX = -34.0, 6.0    # Sul ao Norte
    LON_MIN, LON_MAX = -74.5, -32.0  # Oeste ao Leste
    
    if not (LAT_MIN <= latitude <= LAT_MAX):
        return False, (
            f"Coordenadas fora do território brasileiro "
            f"(latitude {latitude} fora do range {LAT_MIN} a {LAT_MAX})"
        )
    
    if not (LON_MIN <= longitude <= LON_MAX):
        return False, (
            f"Coordenadas fora do território brasileiro "
            f"(longitude {longitude} fora do range {LON_MIN} a {LON_MAX})"
        )
    
    return True, None


def validate_tracking_code(tracking_code: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Valida formato de código de rastreamento
    
    Args:
        tracking_code: Código a validar
    
    Returns:
        Tupla (is_valid, error_message)
    
    Examples:
        >>> validate_tracking_code("ABC123456")
        (True, None)
        
        >>> validate_tracking_code("")
        (False, "Código de rastreamento não pode ser vazio")
    """
    
    if not tracking_code:
        return False, "Código de rastreamento não pode ser vazio"
    
    if not isinstance(tracking_code, str):
        return False, f"Código deve ser string, recebido: {type(tracking_code).__name__}"
    
    # Remove espaços
    tracking_code = tracking_code.strip()
    
    if len(tracking_code) < 3:
        return False, f"Código muito curto (mínimo 3 caracteres): '{tracking_code}'"
    
    if len(tracking_code) > 50:
        return False, f"Código muito longo (máximo 50 caracteres): '{tracking_code}'"
    
    return True, None


def validate_phone_number(phone: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Valida formato de número de telefone brasileiro
    
    Aceita formatos:
    - (21) 98765-4321
    - 21987654321
    - +5521987654321
    
    Args:
        phone: Número de telefone a validar
    
    Returns:
        Tupla (is_valid, error_message)
    """
    
    if not phone:
        return True, None  # Telefone opcional
    
    if not isinstance(phone, str):
        return False, f"Telefone deve ser string, recebido: {type(phone).__name__}"
    
    # Remove caracteres não numéricos
    import re
    digits_only = re.sub(r'\D', '', phone)
    
    # Telefone brasileiro: 10 ou 11 dígitos (com ou sem DDD)
    # 13 dígitos se incluir +55
    if len(digits_only) not in [10, 11, 13]:
        return False, (
            f"Telefone deve ter 10-11 dígitos (ou 13 com +55), "
            f"recebido {len(digits_only)}: '{phone}'"
        )
    
    # Se tem 13 dígitos, deve começar com 55 (código do Brasil)
    if len(digits_only) == 13 and not digits_only.startswith('55'):
        return False, f"Telefone com 13 dígitos deve começar com +55: '{phone}'"
    
    return True, None


def log_validation_error(field: str, value: any, error_message: str):
    """
    Helper para logar erros de validação de forma consistente
    
    Args:
        field: Nome do campo que falhou
        value: Valor que foi rejeitado
        error_message: Mensagem de erro da validação
    """
    logger.warning(
        f"Validação falhou: {field}",
        extra={
            "field": field,
            "value": value,
            "error": error_message,
            "validation": "failed"
        }
    )


# Testes básicos (executar com python -m pytest)
if __name__ == "__main__":
    print("🧪 Testando validadores...")
    
    # Testes de coordenadas
    tests = [
        # (lat, lon, strict, esperado)
        (-22.9068, -43.1729, False, True),   # Rio de Janeiro
        (-23.5505, -46.6333, True, True),    # São Paulo
        (100, 200, False, False),            # Inválido
        (40.7128, -74.0060, True, False),    # Nova York (fora do Brasil)
        (None, None, False, True),           # Opcional
    ]
    
    print("\n📍 Testando validate_coordinates:")
    for lat, lon, strict, expected in tests:
        is_valid, error = validate_coordinates(lat, lon, strict)
        status = "✅" if is_valid == expected else "❌"
        print(f"  {status} ({lat}, {lon}, strict={strict}): {is_valid} - {error}")
    
    # Testes de tracking code
    print("\n📦 Testando validate_tracking_code:")
    tracking_tests = [
        ("ABC123", True),
        ("", False),
        ("AB", False),
        ("A" * 51, False),
    ]
    
    for code, expected in tracking_tests:
        is_valid, error = validate_tracking_code(code)
        status = "✅" if is_valid == expected else "❌"
        print(f"  {status} '{code}': {is_valid} - {error}")
    
    # Testes de telefone
    print("\n📞 Testando validate_phone_number:")
    phone_tests = [
        ("(21) 98765-4321", True),
        ("21987654321", True),
        ("+5521987654321", True),
        ("123", False),
        (None, True),  # Opcional
    ]
    
    for phone, expected in phone_tests:
        is_valid, error = validate_phone_number(phone)
        status = "✅" if is_valid == expected else "❌"
        print(f"  {status} '{phone}': {is_valid} - {error}")
    
    print("\n✅ Testes concluídos!")
