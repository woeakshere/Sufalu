"""
Health check server for monitoring bot status.
Provides HTTP endpoints for health checks and metrics.
"""
import asyncio
from aiohttp import web
import psutil
import socket
import json
import logging
from datetime import datetime
from typing import Dict, Any

from config import PORT, LOG_LEVEL

logger = logging.getLogger(__name__)

# Global references to bot components
bot_components = {
    'transfer_manager': None,
    'searcher': None,
    'cleaner': None
}

async def health_check(request):
    """HTTP endpoint for health checks."""
    health_data = {
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'components': {}
    }
    
    # Check system resources
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        health_data['system'] = {
            'cpu_percent': cpu_percent,
            'memory_percent': memory.percent,
            'memory_available_gb': memory.available / (1024 ** 3),
            'disk_percent': disk.percent,
            'disk_free_gb': disk.free / (1024 ** 3)
        }
        
        # Check if resources are critical
        if cpu_percent > 90:
            health_data['status'] = 'warning'
            health_data['issues'].append('High CPU usage')
        
        if memory.percent > 90:
            health_data['status'] = 'warning'
            health_data['issues'].append('High memory usage')
        
        if disk.percent > 90:
            health_data['status'] = 'warning'
            health_data['issues'].append('Low disk space')
            
    except Exception as e:
        health_data['status'] = 'error'
        health_data['error'] = f'System check failed: {str(e)}'
    
    # Check bot components
    for name, component in bot_components.items():
        if component:
            try:
                if name == 'transfer_manager':
                    stats = component.get_stats()
                    health_data['components'][name] = {
                        'status': 'running',
                        'queue_size': stats['queue_size'],
                        'active_tasks': stats['active_processes'],
                        'processed': stats['total_processed']
                    }
                elif name == 'searcher':
                    health_data['components'][name] = {
                        'status': 'running',
                        'session': 'active' if component._session and not component._session.closed else 'closed'
                    }
                elif name == 'cleaner':
                    usage = component.get_temp_usage()
                    health_data['components'][name] = {
                        'status': 'running',
                        'temp_usage_gb': usage['size_gb'],
                        'temp_files': usage['file_count']
                    }
            except Exception as e:
                health_data['components'][name] = {
                    'status': 'error',
                    'error': str(e)
                }
        else:
            health_data['components'][name] = {'status': 'not_initialized'}
    
    # Check network connectivity
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=5)
        health_data['network'] = 'connected'
    except OSError:
        health_data['network'] = 'disconnected'
        health_data['status'] = 'warning'
    
    return web.json_response(health_data)

async def metrics(request):
    """Prometheus-style metrics endpoint."""
    metrics_data = []
    
    # System metrics
    cpu_percent = psutil.cpu_percent()
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    metrics_data.extend([
        f'system_cpu_percent {cpu_percent}',
        f'system_memory_percent {memory.percent}',
        f'system_memory_available_bytes {memory.available}',
        f'system_disk_percent {disk.percent}',
        f'system_disk_free_bytes {disk.free}'
    ])
    
    # Bot metrics
    if bot_components['transfer_manager']:
        try:
            stats = bot_components['transfer_manager'].get_stats()
            metrics_data.extend([
                f'bot_queue_size {stats["queue_size"]}',
                f'bot_active_tasks {stats["active_processes"]}',
                f'bot_processed_total {stats["total_processed"]}',
                f'bot_failed_total {stats["total_failed"]}',
                f'bot_uptime_seconds {time.time() - stats["start_time"]}'
            ])
        except:
            pass
    
    if bot_components['cleaner']:
        try:
            usage = bot_components['cleaner'].get_temp_usage()
            metrics_data.extend([
                f'bot_temp_usage_bytes {int(usage["size_gb"] * 1024**3)}',
                f'bot_temp_files {usage["file_count"]}'
            ])
        except:
            pass
    
    return web.Response(text='\n'.join(metrics_data), content_type='text/plain')

async def stats(request):
    """Detailed statistics endpoint."""
    stats_data = {
        'timestamp': datetime.utcnow().isoformat(),
        'system': {},
        'bot': {}
    }
    
    # System stats
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    net_io = psutil.net_io_counters()
    
    stats_data['system'] = {
        'cpu': {
            'percent': cpu_percent,
            'cores': psutil.cpu_count(),
            'cores_logical': psutil.cpu_count(logical=True)
        },
        'memory': {
            'total_gb': memory.total / (1024 ** 3),
            'available_gb': memory.available / (1024 ** 3),
            'percent': memory.percent,
            'used_gb': memory.used / (1024 ** 3)
        },
        'disk': {
            'total_gb': disk.total / (1024 ** 3),
            'free_gb': disk.free / (1024 ** 3),
            'percent': disk.percent,
            'used_gb': disk.used / (1024 ** 3)
        },
        'network': {
            'bytes_sent': net_io.bytes_sent,
            'bytes_recv': net_io.bytes_recv,
            'packets_sent': net_io.packets_sent,
            'packets_recv': net_io.packets_recv
        }
    }
    
    # Bot stats
    if bot_components['transfer_manager']:
        tm_stats = bot_components['transfer_manager'].get_stats()
        stats_data['bot']['transfer_manager'] = tm_stats
    
    if bot_components['cleaner']:
        temp_usage = bot_components['cleaner'].get_temp_usage()
        stats_data['bot']['cleanup'] = temp_usage
    
    # Process info
    process = psutil.Process()
    stats_data['process'] = {
        'pid': process.pid,
        'memory_percent': process.memory_percent(),
        'cpu_percent': process.cpu_percent(),
        'threads': process.num_threads(),
        'connections': len(process.connections())
    }
    
    return web.json_response(stats_data)

async def start_health_check():
    """Start the health check server."""
    app = web.Application()
    
    # Add routes
    app.router.add_get('/health', health_check)
    app.router.add_get('/metrics', metrics)
    app.router.add_get('/stats', stats)
    
    # Add root redirect
    async def root(request):
        return web.Response(
            text='Anime Leech Bot Health Check Server\n\n'
                 'Endpoints:\n'
                 '  /health   - Health status\n'
                 '  /metrics  - Prometheus metrics\n'
                 '  /stats    - Detailed statistics'
        )
    
    app.router.add_get('/', root)
    
    # Start server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    
    try:
        await site.start()
        logger.info(f'Health check server started on port {PORT}')
        
        # Keep server running
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info('Health check server stopped')
    finally:
        await runner.cleanup()

def register_component(name: str, component):
    """Register a bot component for health checks."""
    bot_components[name] = component
    logger.debug(f'Registered component for health checks: {name}')