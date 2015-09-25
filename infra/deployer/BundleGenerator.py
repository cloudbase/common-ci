
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
                             git_user_email=None, git_user_name=None, pypi_mirror=None,
                             vmswitch_name=None, vmswitch_management=None,
                             ad_user_name=None, enable_freerdp_console=None):
        hyper_v_options = {'download-mirror': download_mirror,
                           'extra-python-packages': extra_python_packages,
                           'git-user-email': git_user_email,
                           'git-user-name': git_user_name,
                           'pypi-mirror': pypi_mirror,
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
            pypi_mirror='http://64.119.130.115/wheels')

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
            ad_charm = self._get_ad_service(
                nr_units=self.options.nr_ad_units,
                domain_name=self.options.ad_domain_name,
                admin_password=self.options.ad_admin_password)
            ad_charm_dict = {'active-directory': ad_charm}
            bundle_content['nova']['relations'].append([hyper_v_service_name,
                                                        'active-directory'])
            bundle_content['nova']['services'].update(ad_charm_dict)

        return bundle_content
