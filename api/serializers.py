from rest_framework import serializers

class EventoGPSSerializer(serializers.Serializer):
    """ Valida el payload entrante de Divantech """
    patente = serializers.CharField(max_length=20)
    eta = serializers.DateTimeField()
    payload_raw = serializers.JSONField(required=False)

class PesajeRomanaSerializer(serializers.Serializer):
    """ Valida el payload de la nueva API del CII (Romana) """
    patente = serializers.CharField(max_length=20, required=False, allow_blank=True, allow_null=True)
    peso_neto = serializers.DecimalField(max_digits=10, decimal_places=2)
    hora_llegada = serializers.DateTimeField()
    payload_raw = serializers.JSONField(required=False)
