import os
import platform
import gevent

from gevent import subprocess

SYS = platform.system()


def exec_retry(retry=5):
    def wrap(f):
        def wrap_f(*args, **kw):
            count = 0
            err = ""
            while count < retry:
                try:
                    return f(*args, **kw)
                    break
                except Exception as err:
                    gevent.sleep(3)
                    err = err
                    count += 1
            return f(*args, **kw)
        return wrap_f
    return wrap


def is_exe(path):
    if os.path.isfile(path) is False:
        return False
    if SYS == "Windows":
        pathext = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC")
        for i in pathext.split(os.pathsep):
            if path.endswith(i):
                return True
    else:
        if os.access(path, os.X_OK):
            return True
    return False


def which(program):
    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file
    return None


def add_apt_ppa(ppa):
    subprocess.check_call([
        "sudo", "-n", "apt-add-repository", "-y", ppa,
    ])


def install_apt_packages(pkgs):
    apt = ["sudo", "-n", "apt-get", "-y", "--option=Dpkg::Options::=--force-confold", "install"]
    apt.extend(pkgs)
    subprocess.check_call(apt)


def apt_update():
    subprocess.check_call(["sudo", "-n", "apt-get", "update"])


class BundleGenerator(object):
    _AD_GIT_URL       = 'https://github.com/cloudbase/active-directory.git'
    _DEVSTACK_GIT_URL = 'https://github.com/cloudbase/devstack-charm.git'
    _HYPER_V_GIT_URL  = 'https://github.com/cloudbase/hyperv-charm'

    def __init__(self, options):
        self.options = options

    def _get_non_null_values(self, dictionary):
        return dict((key, value) for key, value in dictionary.iteritems()
                    if value is not None)

    def _get_service(self, git_url, charm, nr_units, options):
        return {'branch': git_url,
                'charm': charm,
                'num_units': nr_units,
                'options': self._get_non_null_values(options)}

    def _get_ad_service(self, nr_units, domain_name, admin_password,
                        admin_username=None):
        ad_options = {'domain-name': domain_name,
                      'administrator': admin_username,
                      'password': admin_password}
        return self._get_service(self._AD_GIT_URL,
                                 'local:win2012r2/active-directory',
                                 nr_units, ad_options)

    def _get_hyper_v_service(self, nr_units, download_mirror, extra_python_packages=None,
                             git_user_email=None, git_user_name=None, wheel_mirror=None,
                             ppy_mirror=None, vmswitch_name=None, vmswitch_management=None,
                             ad_user_name=None, enable_freerdp_console=None):
        hyper_v_options = {'download-mirror': download_mirror,
                           'extra-python-packages': extra_python_packages,
                           'git-user-email': git_user_email,
                           'git-user-name': git_user_name,
                           'wheel-mirror': wheel_mirror,
                           'ppy-mirror': ppy_mirror,
                           'vmswitch-name': vmswitch_name,
                           'vmswitch-management': vmswitch_management,
                           'ad-user-name': ad_user_name,
                           'enable-freerdp-console': enable_freerdp_console}
        return self._get_service(self._HYPER_V_GIT_URL,
                                 'local:win2012hvr2/hyper-v-ci',
                                 nr_units, hyper_v_options)

    def _get_devstack_service(self, nr_units, vlan_range, heat_image_url, test_image_url,
                              disabled_services=None, enable_plugins=None,
                              enabled_services=None, extra_packages=None,
                              extra_python_packages=None):
        devstack_options = {'disabled-services': disabled_services,
                            'enable-plugin': enable_plugins,
                            'enabled-services': enabled_services,
                            'extra-packages': extra_packages,
                            'extra-python-packages': extra_python_packages,
                            'heat-image-url': heat_image_url,
                            'test-image-url': test_image_url,
                            'vlan-range': vlan_range}
        return self._get_service(self._DEVSTACK_GIT_URL, 'local:trusty/devstack',
                                 nr_units, devstack_options)

    def _get_overrides_options(self, data_ports, external_ports, zuul_branch, zuul_change,
                               zuul_project, zuul_ref, zuul_url):
        return {'data-port': data_ports,
                'external-port': external_ports,
                'zuul-branch': zuul_branch,
                'zuul-change': zuul_change,
                'zuul-project': zuul_project,
                'zuul-ref': zuul_ref,
                'zuul-url': zuul_url}

    def nova_bundle(self):
        overrides_options = self._get_overrides_options(self.options.data_ports,
            self.options.external_ports, self.options.zuul_branch,
            self.options.zuul_change, self.options.zuul_project,
            self.options.zuul_ref, self.options.zuul_url)

        hyper_v_service = self._get_hyper_v_service(
            nr_units=self.options.nr_hyper_v_units,
            download_mirror='http://64.119.130.115/bin',
            extra_python_packages=self.options.hyper_v_extra_python_packages,
            git_user_email='hyper-v_ci@microsoft.com',
            git_user_name='Hyper-V CI',
            wheel_mirror='http://64.119.130.115/wheels')

        devstack_service = self._get_devstack_service(
            nr_units=self.options.nr_devstack_units,
            disabled_services=self.options.devstack_disabled_services,
            enable_plugins=self.options.devstack_enabled_plugins,
            enabled_services=self.options.devstack_enabled_services,
            extra_packages=self.options.devstack_extra_packages,
            extra_python_packages=self.options.devstack_extra_python_packages,
            heat_image_url='http://10.255.251.230/Fedora.vhdx',
            test_image_url='http://10.255.251.230/cirros.vhdx',
            vlan_range=self.options.vlan_range)

        hyper_v_service_name = 'hyper-v-ci-%s' % self.options.zuul_uuid
        devstack_service_name = 'devstack-%s' % self.options.zuul_uuid
        bundle_content = {
            'nova': {'overrides': overrides_options,
                     'relations': [[devstack_service_name, hyper_v_service_name]],
                     'services': {devstack_service_name: devstack_service,
                                  hyper_v_service_name: hyper_v_service} }
        }

        if self.options.nr_ad_units > 0:
            ad_service_name = "active-directory"
            ad_charm = self._get_ad_service(
                nr_units=self.options.nr_ad_units,
                domain_name=self.options.ad_domain_name,
                admin_password=self.options.ad_admin_password)
            ad_charm_dict = {ad_service_name: ad_charm}
            bundle_content['nova']['relations'].append([hyper_v_service_name,
                                                        ad_service_name])
            bundle_content['nova']['services'].update(ad_charm_dict)

        return bundle_content
