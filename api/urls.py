from django.urls import path
from .views import RecepcionGPSView, RecepcionRomanaView, GanttDataView, SimularPasoView, InitSimulacionView, TaskStatusView, FijarAsignacionView

urlpatterns = [
    path('gps-incoming/', RecepcionGPSView.as_view(), name='gps_incoming'),
    path('romana-incoming/', RecepcionRomanaView.as_view(), name='romana_incoming'),
    path('gantt/', GanttDataView.as_view(), name='gantt_data'),
    path('simular-paso/', SimularPasoView.as_view(), name='simular_paso'),
    path('init-simulacion/', InitSimulacionView.as_view(), name='init_simulacion'),
    path('task-status/<str:task_id>/', TaskStatusView.as_view(), name='task_status'),
    path('asignacion/fijar/', FijarAsignacionView.as_view(), name='fijar_asignacion'),
]
