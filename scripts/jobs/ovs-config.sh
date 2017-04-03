#!/bin/bash

CI_CREDS="ovs-creds.yaml"
domain_name="openvswitch.local"
domain_user="openvswitch"
test_signing="true"
data_port="E4:1D:2D:22:A0:30 E4:1D:2D:22:A6:30 E4:1D:2D:22:A1:E0 24:8A:07:77:3D:00"
external_port="18:A9:05:58:F7:76 00:23:7D:D2:CF:02 00:23:7D:D2:D8:D2 00:23:7D:D2:D8:72"
ZUUL_BRANCH="master"
prep_project="False"
os_data_network="10.12.3.0/24"
hyperv_cherry_picks="https://review.openstack.org/openstack/neutron|refs/changes/41/417141/2|master"
devstack_cherry_picks="https://git.openstack.org/openstack/tempest|refs/changes/49/383049/13|master,https://git.openstack.org/openstack/tempest|refs/changes/28/384528/9|master"
disable_ipv6="false"
win_user="Administrator"
win_password=$(< /dev/urandom tr -dc _A-Z-a-z-0-9 | head -c${1:-24};echo;)
ovs_installer="http://10.20.1.14:8080/ovs/$UUID/OpenvSwitch.msi"
ovs_certificate="http://10.20.1.14:8080/ovs/$UUID/package.cer"
heat_image_url="http://10.20.1.14:8080/cirros-latest.vhdx"
test_image_url="http://10.20.1.14:8080/cirros-latest.vhdx"
scenario_img="cirros-latest.vhdx"
vmswitch_management="false"
hv_extra_python_packages="setuptools SQLAlchemy==0.9.8 wmi oslo.i18n==1.7.0 pbr==1.2.0 oslo.messaging==4.5.1 lxml==3.6.4"
post_python_packages="kombu==4.0.1 amqp==2.1.3 SQLAlchemy==1.0.17"

if [ "$ZUUL_BRANCH" == "stable/mitaka" ]; then
        post_python_packages="oslo.messaging==5.20.0 psutil==1.2.1 kombu==4.0.1 amqp==2.1.3 SQLAlchemy==1.0.17"
fi
