// Personal build profile. Official release signing configuration is unchanged.
const original = require('./package.json').build;
const win = { ...original.win, forceCodeSigning: false, signAndEditExecutable: false };
delete win.signtoolOptions;
delete win.signExts;

module.exports = {
  ...original,
  appId: 'local.wechatdataanalysis.hd',
  productName: 'WeChatDataAnalysis-HD',
  artifactName: 'WeChatDataAnalysis-2.6.0-HD2-Setup.${ext}',
  extraMetadata: {
    name: 'wechat-data-analysis-hd',
    version: '2.6.0-hd.2',
    localImageQualityBuild: true,
  },
  publish: null,
  win,
  nsis: {
    oneClick: false,
    allowToChangeInstallationDirectory: true,
    deleteAppDataOnUninstall: false,
    runAfterFinish: false,
    installerIcon: original.nsis.installerIcon,
    uninstallerIcon: original.nsis.uninstallerIcon,
  },
};
