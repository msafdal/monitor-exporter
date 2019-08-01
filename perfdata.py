import requests, urllib3, json, re
from exporterlog import ExporterLog
import monitorconnection
from requests.auth import HTTPBasicAuth

# Disable InsecureRequestWarning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class Perfdata:
    def __init__(self, query_hostname):
        monitor = monitorconnection.MonitorConfig()
        self.query_hostname = query_hostname
        self.url = 'https://' + monitor.get_host() + '/api/filter/query?query=[services]%20host.name="' + self.query_hostname + '"&columns=host.name,description,perf_data,check_command'
        self.user = monitor.get_user()
        self.passwd = monitor.get_passwd()


    def get_custom_vars(self):
        monitor = monitorconnection.MonitorConfig()
        url = 'https://' + monitor.get_host() + '/api/filter/query?query=[hosts]%20display_name="' + self.query_hostname + '"&columns=custom_variables'

        custom_vars_from_monitor = requests.get(url, auth=HTTPBasicAuth(self.user, self.passwd), verify=False, headers={'Content-Type': 'application/json'})
        custom_vars_json = json.loads(custom_vars_from_monitor.content)

        self.custom_vars = {}
        for var in custom_vars_json:
            self.custom_vars = var['custom_variables']

        return self.custom_vars

    def _get_data(self):
        data_from_monitor = requests.get(self.url, auth=HTTPBasicAuth(self.user, self.passwd), verify=False, headers={'Content-Type': 'application/json'})
        self.data_json = json.loads(data_from_monitor.content)

        ExporterLog.info('API call: ' + data_from_monitor.url)

        if data_from_monitor.status_code == 401:
            ExporterLog.error('Status code: ' + str(data_from_monitor.status_code))
            ExporterLog.error(self.data_json['error'])
            ExporterLog.error(self.data_json['full_error'])
        else:
            ExporterLog.info('Status code: ' + str(data_from_monitor.status_code))

        ExporterLog.info('Elapsed time: ' + str(data_from_monitor.elapsed))

        if len(data_from_monitor.content) > 2:
            ExporterLog.info('Received perfdata from Monitor')
        else:
            ExporterLog.error('Received no perfdata from Monitor')
        return self.data_json

    def get_perfdata(self):
        monitor = monitorconnection.MonitorConfig()
        self._get_data()
        
        labels = monitor.get_labels()
        monitor_custom_vars = Perfdata(self.query_hostname).get_custom_vars()
        new_labels = {}
        if len(monitor_custom_vars) > 0:
            monitor_custom_vars = {k.lower(): v for k, v in monitor_custom_vars.items()}
            for i in labels.keys():
                if i in monitor_custom_vars.keys():
                    new_labels.update({labels[i]: monitor_custom_vars[i]})

        self.perfdatadict = {}
        check_command_regex = re.compile(r'^.+?[^!\n]+')

        for item in self.data_json:
            if 'perf_data' in item and item['perf_data'] != []:
                perfdata = item['perf_data']

            for key, value in perfdata.items():
                for nested_key, nested_value in value.items():
                    if nested_key == 'unit' and nested_value == 'ms':
                        value['value'] = value['value'] / 1000.0
                        key = key + '_seconds'

                    if nested_key == 'unit' and nested_value == 's':
                        key = key + '_seconds'

                    if nested_key == 'unit' and nested_value == '%':
                        value['value'] = value['value'] / 100.0
                        key = key + '_ratio'

                    if nested_key == 'unit' and nested_value == 'B':
                        key = key + '_bytes'

                for nested_key, nested_value in value.items():
                    if nested_key == 'value':
                        check_command = check_command_regex.search(item['check_command'])
                        prometheus_key = monitor.get_prefix() + check_command.group() + '_' + key.lower()
                        prometheus_key = prometheus_key.replace(' ', '_')
                        prometheus_key = prometheus_key.replace('/', 'slash')
                        prometheus_key = prometheus_key.replace('%', 'percent')
                        if new_labels == None:
                            prometheus_key = prometheus_key + '{hostname="' + item['host']['name'] + '"' + ', service="' + item['description'] + '"}'
                        else:
                            labelstring = ''
                            for label_key, label_value in new_labels.items():
                                labelstring += ', ' + label_key + '="' + label_value + '"'
                            prometheus_key = prometheus_key + '{hostname="' + item['host']['name'] + '"' + ', service="' + item['description'] + '"' + labelstring + '}'

                        self.perfdatadict.update({prometheus_key: str(nested_value)})

        return self.perfdatadict

    def prometheus_format(self):
        metrics = ''
        for key, value in self.perfdatadict.items():
            metrics += key + ' ' + value + '\n'

        return metrics